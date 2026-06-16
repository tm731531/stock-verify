"""順格局 ORB 交易卡: 給一天的資料, 產出今日格局/基準/進場/停利停損/結果。

格局用『前一交易日』的 MA20/MA60(開盤時可知, 不偷看當日)。只在格局方向出手。
"""
from dataclasses import dataclass
import pandas as pd

from orbital_yang.regime import alignment_sign
from orbital_yang.orb import run_orb, ORBParams


@dataclass
class TradeCard:
    date: str
    regime: int           # +1 多 / -1 空 / 0 無格局
    ref_high: float
    ref_low: float
    has_trade: bool       # 是否有『順格局』訊號
    direction: str        # 'long'/'short'/''
    entry_time: str
    entry: float
    stop: float
    tp: float
    exit_time: str
    exit: float
    pnl: float
    reason: str


def _prior_regime(daily_df, date_str: str, fast: int = 20, slow: int = 60) -> int:
    """取 date_str 之前最後一個交易日的格局方向(避免偷看當日)。"""
    sign = alignment_sign(daily_df, fast, slow)
    d = pd.to_datetime(daily_df["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    prior = [i for i in range(len(d)) if d[i] < date_str]
    return int(sign[prior[-1]]) if prior else 0


def trade_card(daily_df, min1_df, date_str: str, params: ORBParams = ORBParams()) -> TradeCard:
    regime = _prior_regime(daily_df, date_str)
    m = min1_df.copy()
    m["ts"] = pd.to_datetime(m["ts"])
    m["d"] = m["ts"].dt.strftime("%Y-%m-%d")
    day = m[m["d"] == date_str]
    if not len(day):
        return TradeCard(date_str, regime, 0.0, 0.0, False, "", "", 0.0, 0.0, 0.0, "", 0.0, 0.0, "")
    trades = run_orb(day, params)
    # 基準 = 當日第一根日盤K
    t = day["ts"].dt.strftime("%H:%M")
    sess = day[(t >= params.session_start) & (t <= params.session_end)].sort_values("ts")
    ref_high = float(sess.iloc[0]["High"]) if len(sess) else 0.0
    ref_low = float(sess.iloc[0]["Low"]) if len(sess) else 0.0
    if trades:
        tr = trades[0]
        aligned = regime == (1 if tr.direction == "long" else -1)
        if aligned:
            stop = tr.ref_low if tr.direction == "long" else tr.ref_high
            return TradeCard(date_str, regime, tr.ref_high, tr.ref_low, True, tr.direction,
                             tr.entry_time, tr.entry, stop,
                             tr.entry + params.take_profit if tr.direction == "long" else tr.entry - params.take_profit,
                             tr.exit_time, tr.exit, tr.pnl, tr.reason)
    return TradeCard(date_str, regime, ref_high, ref_low, False, "", "", 0.0, 0.0, 0.0, "", 0.0, 0.0, "")
