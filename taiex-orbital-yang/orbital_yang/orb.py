"""軌道鞅 開盤 ORB 當沖回測引擎 (盤中 1分K)。

開盤第一根(8:46)定基準高/低 -> 之後 1分K 收破基準高做多/破低做空;
停損=基準K高低點, 停利=+50點(2滿), 收盤未觸發以最後一根收盤平倉。每日一筆。
詭道一致: 進場看收盤; 停損/停利為掛單, 以盤中 High/Low 觸發。
"""
from dataclasses import dataclass
import pandas as pd


@dataclass
class ORBParams:
    take_profit: float = 50.0
    session_start: str = "08:45"
    session_end: str = "13:45"


@dataclass
class ORBTrade:
    date: object
    direction: str       # 'long' / 'short'
    entry_time: str
    entry: float
    exit_time: str
    exit: float
    pnl: float           # 點數 (依方向, 正=賺)
    reason: str          # 'tp' / 'stop' / 'eod'
    ref_high: float
    ref_low: float


@dataclass
class ORBPerf:
    n: int
    n_win: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float
    total_pnl: float
    n_tp: int
    n_stop: int
    n_eod: int


def _mk(date, direction, etime, entry, xtime, xprice, reason, rh, rl):
    pnl = (xprice - entry) if direction == "long" else (entry - xprice)
    return ORBTrade(date, direction, etime, entry, xtime, xprice, float(pnl), reason, rh, rl)


def run_orb(df: pd.DataFrame, params: ORBParams = ORBParams()) -> list:
    """df 需欄位 ts, Open, High, Low, Close (ts 可轉 datetime)。回傳每日 ORBTrade。"""
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    trades = []
    for d, g in df.groupby("date"):
        t = g["ts"].dt.strftime("%H:%M")
        g = g[(t >= params.session_start) & (t <= params.session_end)].sort_values("ts").reset_index(drop=True)
        if len(g) < 2:
            continue
        ref = g.iloc[0]
        ref_high, ref_low = float(ref["High"]), float(ref["Low"])
        pos = None
        trade = None
        for i in range(1, len(g)):
            bar = g.iloc[i]
            tm = bar["ts"].strftime("%H:%M")
            h, l, c = float(bar["High"]), float(bar["Low"]), float(bar["Close"])
            if pos is None:
                if c > ref_high:
                    pos = ("long", c, ref_low, c + params.take_profit, tm)
                elif c < ref_low:
                    pos = ("short", c, ref_high, c - params.take_profit, tm)
            else:
                direction, entry, stop, tp, etime = pos
                if direction == "long":
                    if l <= stop:
                        trade = _mk(d, direction, etime, entry, tm, stop, "stop", ref_high, ref_low); break
                    if h >= tp:
                        trade = _mk(d, direction, etime, entry, tm, tp, "tp", ref_high, ref_low); break
                else:
                    if h >= stop:
                        trade = _mk(d, direction, etime, entry, tm, stop, "stop", ref_high, ref_low); break
                    if l <= tp:
                        trade = _mk(d, direction, etime, entry, tm, tp, "tp", ref_high, ref_low); break
        if pos is not None and trade is None:
            direction, entry, stop, tp, etime = pos
            last = g.iloc[-1]
            trade = _mk(d, direction, etime, entry, last["ts"].strftime("%H:%M"),
                        float(last["Close"]), "eod", ref_high, ref_low)
        if trade:
            trades.append(trade)
    return trades


def summarize_orb(trades: list) -> ORBPerf:
    if not trades:
        return ORBPerf(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0)
    import numpy as np
    pnls = np.array([t.pnl for t in trades], float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(trades)
    n_win = int((pnls > 0).sum())
    return ORBPerf(
        n, n_win, n_win / n,
        float(wins.mean()) if len(wins) else 0.0,
        float(losses.mean()) if len(losses) else 0.0,
        float(pnls.mean()), float(pnls.sum()),
        sum(t.reason == "tp" for t in trades),
        sum(t.reason == "stop" for t in trades),
        sum(t.reason == "eod" for t in trades),
    )
