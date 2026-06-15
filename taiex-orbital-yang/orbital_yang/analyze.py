"""Step 2 壓力分析: 抓下殺段、多空拆解、區間損益、策略權益回撤。"""
import numpy as np


def drawdown_series(closes) -> np.ndarray:
    """每根的回撤 = close / 歷史高 - 1 (<=0)。"""
    closes = np.asarray(closes, dtype=float)
    peak = np.maximum.accumulate(closes)
    return closes / peak - 1.0


def find_selloffs(closes, min_drop: float = 0.05):
    """找出峰到谷跌幅 >= min_drop 的下殺段。

    回傳 list of (peak_idx, trough_idx, drop)，drop 為負值 (e.g. -0.08)。
    每段以『創新高』為界，記錄該波段最低點。
    """
    closes = np.asarray(closes, dtype=float)
    episodes = []
    peak_idx = 0
    peak = closes[0]
    trough_idx = 0
    trough = closes[0]
    for i in range(1, len(closes)):
        if closes[i] > peak:
            if trough_idx > peak_idx and (trough / peak - 1.0) <= -min_drop:
                episodes.append((peak_idx, trough_idx, trough / peak - 1.0))
            peak = closes[i]
            peak_idx = i
            trough = closes[i]
            trough_idx = i
        elif closes[i] < trough:
            trough = closes[i]
            trough_idx = i
    if trough_idx > peak_idx and (trough / peak - 1.0) <= -min_drop:
        episodes.append((peak_idx, trough_idx, trough / peak - 1.0))
    return episodes


def down_regime_mask(df, lookback: int = 20) -> np.ndarray:
    """布林: 該根的前 lookback 根報酬 < 0 視為下跌動能區間。前 lookback 根為 False。"""
    c = df["close"].to_numpy(float)
    mask = np.zeros(len(c), dtype=bool)
    if len(c) > lookback:
        trailing = c[lookback:] / c[:-lookback] - 1.0
        mask[lookback:] = trailing < 0.0
    return mask


def trades_in_episodes(trades, episodes):
    """進場索引落在任一下殺段 [peak_idx, trough_idx] 內的交易。"""
    spans = [(p, tr) for (p, tr, _d) in episodes]
    return [t for t in trades if any(p <= t.entry_idx <= tr for (p, tr) in spans)]


def split_long_short(trades):
    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]
    return longs, shorts


def split_by_down_regime(df, trades, lookback: int = 20):
    mask = down_regime_mask(df, lookback)
    down = [t for t in trades if mask[t.entry_idx]]
    up = [t for t in trades if not mask[t.entry_idx]]
    return up, down


def equity_max_drawdown(trades) -> float:
    """策略權益曲線(依成交順序累積點數)的最大回撤(負值, 點)。"""
    if not trades:
        return 0.0
    eq = np.concatenate([[0.0], np.cumsum([t.pnl for t in trades])])
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())
