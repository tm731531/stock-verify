"""Step 2: 詭道方向性策略回測 (關卡過破進場 + 底頂部停損 + 滿足點停利)。

詭道一致性: 進出場判定一律用『收盤』(實體), 不看 high/low 影線。
"""
from dataclasses import dataclass
import numpy as np

from .body_levels import Level


@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    direction: str       # 'long' | 'short'
    entry: float
    exit: float
    pnl: float           # 點數, 已依方向調整 (正=賺)
    reason: str          # 'target' | 'stop' | 'timeout'


@dataclass
class BacktestParams:
    breakout_pct: float      # 收盤突破關卡多少比例算過破 (e.g. 0.001)
    stop_buffer_pct: float   # 停損放在被破關卡的反向緩衝 (e.g. 0.003)
    target_mult: float       # 滿足點 = 進場 +/- target_mult * 關卡K實體 (測幅)
    max_hold: int            # 最多持有幾根, 逾時以收盤平倉


@dataclass
class Performance:
    n_trades: int
    n_win: int
    win_rate: float
    avg_win: float
    avg_loss: float
    payoff: float          # avg_win / |avg_loss|
    expectancy: float      # 每筆期望點數
    total_pnl: float


def run_backtest(df, levels, params: BacktestParams) -> list:
    c = df["close"].to_numpy(float)
    o = df["open"].to_numpy(float)
    body = np.abs(c - o)
    n = len(c)
    lv_sorted = sorted(levels, key=lambda L: L.idx)

    trades = []
    t = 1
    while t < n:
        entered = None
        for L in lv_sorted:
            if L.idx >= t:        # 關卡尚未形成
                continue
            price = L.price
            b = body[L.idx]
            if L.kind == "resistance":   # 過: 向上突破壓力 -> 做多
                if c[t] >= price * (1 + params.breakout_pct) and c[t - 1] < price:
                    stop = price * (1 - params.stop_buffer_pct)
                    target = c[t] + params.target_mult * b
                    entered = ("long", c[t], stop, target)
                    break
            else:                        # 破: 向下跌破支撐 -> 做空
                if c[t] <= price * (1 - params.breakout_pct) and c[t - 1] > price:
                    stop = price * (1 + params.stop_buffer_pct)
                    target = c[t] - params.target_mult * b
                    entered = ("short", c[t], stop, target)
                    break
        if entered is None:
            t += 1
            continue

        direction, entry, stop, target = entered
        exit_idx = min(n - 1, t + params.max_hold)
        reason = "timeout"
        for u in range(t + 1, min(n, t + params.max_hold + 1)):
            if direction == "long":
                if c[u] <= stop:
                    exit_idx, reason = u, "stop"
                    break
                if c[u] >= target:
                    exit_idx, reason = u, "target"
                    break
            else:
                if c[u] >= stop:
                    exit_idx, reason = u, "stop"
                    break
                if c[u] <= target:
                    exit_idx, reason = u, "target"
                    break
        exit_price = c[exit_idx]
        pnl = (exit_price - entry) if direction == "long" else (entry - exit_price)
        trades.append(Trade(t, exit_idx, direction, entry, exit_price, pnl, reason))
        t = exit_idx + 1     # 平倉後才找下一筆 (單一持倉)
    return trades


def summarize(trades: list) -> Performance:
    if not trades:
        return Performance(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pnls = np.array([tr.pnl for tr in trades], float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(trades)
    n_win = int((pnls > 0).sum())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
    expectancy = float(pnls.mean())
    return Performance(n, n_win, n_win / n, avg_win, avg_loss, payoff,
                       expectancy, float(pnls.sum()))
