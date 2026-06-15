"""簡化 Black-Scholes 選擇權買方模型 (r=0)。

只當買方: 做多訊號買 CALL、做空訊號買 PUT, 進場權利金校準到 ~target_premium 點。
最大虧損 = 權利金。到期前訊號未了結則以到期內含價值結算 (誠實反映 theta/歸零)。
買方用倍數思考: 報告 2x/3x 命中率與歸零率。
"""
from dataclasses import dataclass
from math import log, sqrt, erf
import numpy as np

from .backtest import Trade


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def bs_price(S: float, K: float, T: float, sigma: float, kind: str) -> float:
    """歐式選擇權 BS 價 (r=0)。T 為年; T<=0 或 sigma<=0 回內含價值。"""
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    d1 = (log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if kind == "call":
        return S * _norm_cdf(d1) - K * _norm_cdf(d2)
    return K * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def solve_strike(S: float, T: float, sigma: float, kind: str, target_premium: float) -> float:
    """二分搜尋出讓進場權利金 ~ target_premium 的價外履約價。"""
    if kind == "call":
        lo, hi = S, S * 1.5          # call: K 越高權利金越低
    else:
        lo, hi = S * 0.5, S          # put: K 越低權利金越低
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        p = bs_price(S, mid, T, sigma, kind)
        if kind == "call":
            if p > target_premium:
                lo = mid
            else:
                hi = mid
        else:
            if p > target_premium:
                hi = mid
            else:
                lo = mid
    return 0.5 * (lo + hi)


@dataclass
class OptionParams:
    iv: float                   # 年化隱含波動
    expiry_days: int            # 進場時剩餘到期 (交易日)
    target_premium: float       # 進場權利金 (點), e.g. 30
    point_value: float = 50.0   # TXO 1 點 = NT$50
    half_spread_pts: float = 0.0    # 半個買賣價差(點): 買付 +half, 賣收 -half
    commission_ntd: float = 0.0     # 單邊手續費(NT$/口)


@dataclass
class OptionTrade:
    direction: str              # 'long'(call) / 'short'(put)
    kind: str                   # 'call' / 'put'
    entry_premium: float
    exit_premium: float
    pnl: float                  # 點 (exit - entry)
    mult: float                 # exit/entry 倍數
    expired_worthless: bool


@dataclass
class OptionPerformance:
    n_trades: int
    n_win: int
    win_rate: float             # pnl>0 比例
    avg_win: float
    avg_loss: float
    payoff: float
    expectancy: float           # 點/筆
    roi: float                  # expectancy / 平均進場權利金
    total_pnl: float
    rate_2x: float              # 達 >=2 倍比例
    rate_3x: float              # 達 >=3 倍比例
    worthless_rate: float       # 歸零比例
    max_drawdown: float         # 點


def simulate_option_trades(df, trades, params: OptionParams) -> list:
    c = df["close"].to_numpy(float)
    n = len(c)
    yr = 252.0
    out = []
    for tr in trades:
        kind = "call" if tr.direction == "long" else "put"
        S0 = c[tr.entry_idx]
        T0 = params.expiry_days / yr
        sigma = params.iv
        K = solve_strike(S0, T0, sigma, kind, params.target_premium)
        entry_prem = bs_price(S0, K, T0, sigma, kind)
        expiry_bar = min(n - 1, tr.entry_idx + params.expiry_days)
        exit_bar = min(tr.exit_idx, expiry_bar)
        held = exit_bar - tr.entry_idx
        T_exit = max(0.0, (params.expiry_days - held) / yr)
        S_exit = c[exit_bar]
        exit_prem = bs_price(S_exit, K, T_exit, sigma, kind)
        worthless = exit_prem <= 1e-6
        commission_pts = params.commission_ntd / params.point_value
        paid = entry_prem + params.half_spread_pts + commission_pts
        if worthless:
            received = 0.0                      # 放到期歸零, 不賣 -> 無出場成本
        else:
            received = max(0.0, exit_prem - params.half_spread_pts - commission_pts)
        pnl = received - paid
        mult = (exit_prem / entry_prem) if entry_prem > 1e-9 else 0.0   # 倍數用毛權利金(他的語言)
        out.append(OptionTrade(tr.direction, kind, entry_prem, exit_prem, pnl,
                               mult, worthless))
    return out


def summarize_options(otrades: list) -> OptionPerformance:
    if not otrades:
        return OptionPerformance(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                 0.0, 0.0, 0.0, 0.0)
    pnls = np.array([t.pnl for t in otrades], float)
    prem = np.array([t.entry_premium for t in otrades], float)
    mults = np.array([t.mult for t in otrades], float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(otrades)
    n_win = int((pnls > 0).sum())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
    exp = float(pnls.mean())
    roi = exp / float(prem.mean()) if prem.mean() > 0 else 0.0
    eq = np.concatenate([[0.0], np.cumsum(pnls)])
    mdd = float((eq - np.maximum.accumulate(eq)).min())
    return OptionPerformance(
        n, n_win, n_win / n, avg_win, avg_loss, payoff, exp, roi, float(pnls.sum()),
        float((mults >= 2.0).mean()), float((mults >= 3.0).mean()),
        float(sum(t.expired_worthless for t in otrades)) / n, mdd,
    )
