"""ORB 真實成本 + 真實選擇權買方對映。

期貨成本: 滑價(點/邊) + 手續費(NT$/邊)。
選擇權買方: 進場=當日該檔 option 開盤, 出場界 = 收盤(base) / 當日最高(best); 含選擇權成本。
全用真實成交價(FinMind 日線選擇權 OHLC), 不用模型。
"""
from dataclasses import dataclass
import pandas as pd


def apply_futures_cost(pnl_points: float, slippage_pts: float, commission_ntd: float,
                       point_value: float = 200.0) -> float:
    """期貨單筆淨損益(點) = 毛 - 來回(滑價 + 手續費換點)。"""
    comm_pts = commission_ntd / point_value
    return pnl_points - 2.0 * (slippage_pts + comm_pts)


def option_ohlc(chain: pd.DataFrame, contract_date: str, strike_price: float, call_put: str):
    """取某日鏈裡指定合約的 open/high/low/close (日盤優先)。找不到回 None。"""
    if chain is None or not len(chain):
        return None
    c = chain
    if "trading_session" in c.columns:
        day = c[c["trading_session"] != "after_market"]
        c = day if len(day) else c
    c = c[(c["contract_date"].astype(str) == str(contract_date)) & (c["call_put"] == call_put)]
    c = c[pd.to_numeric(c["strike_price"], errors="coerce") == strike_price]
    if not len(c):
        return None
    r = c.iloc[0]
    g = lambda k: float(pd.to_numeric(pd.Series([r[k]]), errors="coerce").iloc[0])
    return {"open": g("open"), "high": g("max"), "low": g("min"), "close": g("close")}


def buyer_pnl(entry_open: float, exit_px: float, half_spread_pts: float,
              commission_ntd: float, point_value: float = 50.0):
    """選擇權買方單筆淨損益(點)。買付 open+成本; 賣收 max(0, exit-成本)。"""
    comm_pts = commission_ntd / point_value
    paid = entry_open + half_spread_pts + comm_pts
    received = max(0.0, exit_px - half_spread_pts - comm_pts)
    return received - paid


@dataclass
class BuyerSummary:
    n: int
    base_roi: float       # open->close
    best_roi: float       # open->high
    base_expectancy: float
    best_expectancy: float
    base_winrate: float
    avg_entry_premium: float


def summarize_buyer(rows: list) -> BuyerSummary:
    """rows: list of dict(entry, base_pnl, best_pnl)。"""
    import numpy as np
    if not rows:
        return BuyerSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ent = np.array([r["entry"] for r in rows], float)
    base = np.array([r["base_pnl"] for r in rows], float)
    best = np.array([r["best_pnl"] for r in rows], float)
    avg_ent = float(ent.mean())
    return BuyerSummary(
        len(rows),
        float(base.mean()) / avg_ent if avg_ent else 0.0,
        float(best.mean()) / avg_ent if avg_ent else 0.0,
        float(base.mean()), float(best.mean()),
        float((base > 0).mean()), avg_ent,
    )
