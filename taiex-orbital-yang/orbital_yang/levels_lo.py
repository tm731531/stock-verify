"""軌道鞅執行式回測: 在前一盤關卡(昨開高低收)順大小流氓掛限價單, 回測成交, 停損50, 同日停利。"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from orbital_yang.regime import alignment_sign


@dataclass
class LOParams:
    take_profit: float = 50.0
    stop: float = 50.0
    session_start: str = "08:45"
    session_end: str = "13:45"


@dataclass
class LOTrade:
    date: str
    direction: str        # 'long'/'short'
    line_label: str       # '昨低'/'昨收'/...
    line: float
    entry_time: str
    entry: float
    exit_time: str
    exit: float
    pnl: float
    reason: str           # 'tp'/'stop'/'eod'


_LABELS = [("昨開", "open"), ("昨高", "high"), ("昨低", "low"), ("昨收", "close")]


def prior_levels(daily_df, date_str):
    """回傳 date_str 前一交易日的 (label, price) 清單; 無前日回 []。"""
    d = pd.to_datetime(daily_df["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    prior = [i for i in range(len(d)) if d[i] < date_str]
    if not prior:
        return []
    row = daily_df.iloc[prior[-1]]
    return [(lab, float(row[col])) for lab, col in _LABELS]


def run_lo(daily_df, min1_df, params: LOParams = LOParams()) -> list:
    sign = alignment_sign(daily_df, 20, 60)
    dd = pd.to_datetime(daily_df["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    prior_sign = {}
    for k in range(len(dd)):
        before = [i for i in range(len(dd)) if dd[i] < dd[k]]
        prior_sign[dd[k]] = int(sign[before[-1]]) if before else 0

    m = min1_df.copy()
    m["ts"] = pd.to_datetime(m["ts"])
    m["d"] = m["ts"].dt.strftime("%Y-%m-%d")
    trades = []
    for date_str, g in m.groupby("d"):
        regime = prior_sign.get(date_str, 0)
        if regime == 0:
            continue
        levels = prior_levels(daily_df, date_str)
        if not levels:
            continue
        t = g["ts"].dt.strftime("%H:%M")
        sess = g[(t >= params.session_start) & (t <= params.session_end)].sort_values("ts").reset_index(drop=True)
        if len(sess) < 2:
            continue
        op = float(sess.iloc[0]["Open"])
        if regime == 1:
            cand = [(lab, p) for lab, p in levels if p < op]
            if not cand:
                continue
            lab, line = max(cand, key=lambda x: x[1])     # 最近的下方支撐
        else:
            cand = [(lab, p) for lab, p in levels if p > op]
            if not cand:
                continue
            lab, line = min(cand, key=lambda x: x[1])     # 最近的上方壓力
        H = sess["High"].to_numpy(float); L = sess["Low"].to_numpy(float)
        C = sess["Close"].to_numpy(float); TS = sess["ts"]
        n = len(sess)
        entered = None
        trade = None
        for i in range(1, n):
            tm = TS.iloc[i].strftime("%H:%M")
            if entered is None:
                touched = (L[i] <= line) if regime == 1 else (H[i] >= line)
                if touched:
                    if regime == 1:
                        entered = ("long", line, line - params.stop, line + params.take_profit, tm)
                    else:
                        entered = ("short", line, line + params.stop, line - params.take_profit, tm)
            else:
                direction, entry, stop, tp, etime = entered
                if direction == "long":
                    if L[i] <= stop:
                        trade = ("long", lab, line, etime, entry, tm, stop, "stop"); break
                    if H[i] >= tp:
                        trade = ("long", lab, line, etime, entry, tm, tp, "tp"); break
                else:
                    if H[i] >= stop:
                        trade = ("short", lab, line, etime, entry, tm, stop, "stop"); break
                    if L[i] <= tp:
                        trade = ("short", lab, line, etime, entry, tm, tp, "tp"); break
        if entered is not None and trade is None:
            direction, entry, stop, tp, etime = entered
            trade = (direction, lab, line, etime, entry, TS.iloc[-1].strftime("%H:%M"),
                     float(C[-1]), "eod")
        if trade:
            direction, lab2, line2, etime, entry, xtime, xprice, reason = trade
            pnl = (xprice - entry) if direction == "long" else (entry - xprice)
            trades.append(LOTrade(date_str, direction, lab2, line2, etime, entry,
                                  xtime, float(xprice), float(pnl), reason))
    return trades


def summarize_lo(trades, slippage=1.0, commission=40.0, pv=200.0):
    if not trades:
        return {}
    net = np.array([apply_cost(t.pnl, slippage, commission, pv) for t in trades], float)
    wins = net > 0
    eq = np.concatenate([[0.0], np.cumsum(net)])
    maxdd = float((eq - np.maximum.accumulate(eq)).min())
    return dict(n=len(trades), win_rate=float(wins.mean()), net_exp=float(net.mean()),
                total=float(net.sum()), avg_win=float(net[wins].mean()) if wins.any() else 0.0,
                avg_loss=float(net[~wins].mean()) if (~wins).any() else 0.0,
                maxdd=maxdd, n_tp=sum(t.reason=="tp" for t in trades),
                n_stop=sum(t.reason=="stop" for t in trades), n_eod=sum(t.reason=="eod" for t in trades),
                net=net)


def apply_cost(pnl, slippage, commission, pv):
    return pnl - 2.0 * (slippage + commission / pv)
