"""
深度分析：
1. MA濾網正式測試 (MA10/MA20/MA60, 無濾網)
2. 2023年問題根源解剖
3. Calmar > 3 策略探索
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v6d import (
    load_data, prepare_data, scan_signals,
    StrategyConfig, Signal, Position, Trade, PortfolioResult
)

DB_PATH = Path(__file__).parent.parent / 'data' / 'tdcc_holdings.db'

# ── 通用模擬核心（支援多種濾網和出場參數）────────────────
def simulate(signals, price_idx, prices, cfg,
             ma_period=None,       # 個股 MA 濾網週期 (None=關閉)
             stop_loss=None,       # 覆蓋 stop_loss_pct
             trail_activate=None,  # 覆蓋 trailing_activate_pct
             trail_stop=None,      # 覆蓋 trailing_stop_pct
             max_hold=None,        # 覆蓋 max_hold_days
             min_r400=None,        # 覆蓋進場門檻
             date_range=None,      # (start_yyyymmdd, end_yyyymmdd)
             circuit_breaker=None  # 滾動勝率<此值時暫停 (e.g. 0.3)
             ):
    """通用回測核心"""
    # 合並參數覆蓋
    sl = stop_loss if stop_loss is not None else cfg.stop_loss_pct
    ta = trail_activate if trail_activate is not None else cfg.trailing_activate_pct
    ts = trail_stop if trail_stop is not None else cfg.trailing_stop_pct
    mh = max_hold if max_hold is not None else cfg.max_hold_days

    # 建立個股 MA 索引
    ma_idx = {}
    if ma_period:
        for code, parr in price_idx.items():
            if len(parr) >= ma_period:
                closes = parr[:, 1].astype(float)
                ma = pd.Series(closes).rolling(ma_period).mean().values
                ma_idx[code] = np.column_stack([parr[:, 0], ma])

    # 過濾訊號
    filtered_signals = signals
    if min_r400:
        filtered_signals = [s for s in signals if s.r400_chg >= min_r400]
    if date_range:
        s_date, e_date = date_range
        filtered_signals = [s for s in filtered_signals
                            if s_date <= s.buy_date <= e_date]

    # MA 過濾
    if ma_period:
        ma_ok = []
        for s in filtered_signals:
            if s.code not in ma_idx:
                continue
            marr = ma_idx[s.code]
            # 找訊號日的 MA 值
            idx = np.searchsorted(marr[:, 0], s.buy_date)
            if idx >= len(marr):
                idx = len(marr) - 1
            # 找最近有效 MA
            found = False
            for k in range(idx, max(idx-5, -1), -1):
                if k >= 0 and not np.isnan(marr[k, 1]):
                    # 找當日收盤價
                    parr = price_idx[s.code]
                    pi = np.searchsorted(parr[:, 0], s.buy_date)
                    if pi >= len(parr):
                        pi = len(parr) - 1
                    close = float(parr[pi, 1])
                    ma_val = float(marr[k, 1])
                    if close >= ma_val:
                        ma_ok.append(s)
                    found = True
                    break
            if not found:
                pass  # 無法判斷，跳過
        filtered_signals = ma_ok

    cash = cfg.capital
    positions = []
    trades = []
    held_codes = set()
    weekly_entries = defaultdict(int)
    recent_results = []  # 熔斷用：最近N筆結果

    sig_by_date = defaultdict(list)
    for s in filtered_signals:
        sig_by_date[s.buy_date].append(s)

    all_trade_dates = sorted(prices['date'].unique())
    if date_range:
        s_date, e_date = date_range
        all_trade_dates = [d for d in all_trade_dates if s_date <= d <= e_date]

    equity_records = []
    paused_by_cb = False

    for date in all_trade_dates:
        new_positions = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None:
                new_positions.append(pos)
                continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_positions.append(pos)
                continue

            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)

            ret_pct = (cp - pos.buy_price) / pos.buy_price * 100
            drawdown_pct = (cp - pos.peak_price) / pos.peak_price * 100
            peak_gain_pct = (pos.peak_price - pos.buy_price) / pos.buy_price * 100

            exit_reason = None
            if ret_pct <= sl:
                exit_reason = '停損'
            elif peak_gain_pct >= ta and drawdown_pct <= -ts:
                exit_reason = '停利' if ret_pct > 0 else '追蹤停損'
            elif pos.days_held >= mh:
                exit_reason = '到期'

            if exit_reason:
                sell_value = pos.shares * cp
                net_proceeds = sell_value * (1 - cfg.sell_cost_rate)
                profit = net_proceeds - pos.cost_basis
                cash += net_proceeds
                held_codes.discard(pos.code)
                t = Trade(
                    code=pos.code, buy_date=pos.buy_date, sell_date=date,
                    buy_price=pos.buy_price, sell_price=cp, shares=pos.shares,
                    return_pct=ret_pct, profit=profit, days_held=pos.days_held,
                    exit_reason=exit_reason, peak_price=pos.peak_price,
                )
                trades.append(t)
                recent_results.append(1 if profit > 0 else 0)
            else:
                new_positions.append(pos)
        positions = new_positions

        # 熔斷判斷
        if circuit_breaker and len(recent_results) >= 10:
            rolling_wr = sum(recent_results[-10:]) / 10
            paused_by_cb = rolling_wr < circuit_breaker
        else:
            paused_by_cb = False

        if date in sig_by_date and not paused_by_cb:
            week_key = date[:6]
            for sig in sig_by_date[date]:
                if sig.code in held_codes:
                    continue
                if len(positions) >= cfg.max_positions:
                    continue
                if cash < cfg.per_position:
                    continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week:
                    continue
                shares = int(cfg.per_position / sig.buy_price)
                if shares <= 0:
                    continue
                cost_basis = shares * sig.buy_price * (1 + cfg.buy_fee_rate)
                if cost_basis > cash:
                    continue
                cash -= cost_basis
                positions.append(Position(
                    code=sig.code, buy_date=date, buy_price=sig.buy_price,
                    shares=shares, cost_basis=cost_basis, peak_price=sig.buy_price,
                ))
                held_codes.add(sig.code)
                weekly_entries[week_key] += 1

        portfolio_value = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                if idx < len(parr) and parr[idx, 0] == date:
                    portfolio_value += pos.shares * float(parr[idx, 1])
                else:
                    portfolio_value += pos.shares * pos.buy_price
            else:
                portfolio_value += pos.shares * pos.buy_price
        equity_records.append({'date': date, 'value': portfolio_value, 'n_positions': len(positions)})

    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret_pct = (cp - pos.buy_price) / pos.buy_price * 100
        profit = pos.shares * cp - pos.cost_basis
        trades.append(Trade(
            code=pos.code, buy_date=pos.buy_date, sell_date='OPEN',
            buy_price=pos.buy_price, sell_price=cp, shares=pos.shares,
            return_pct=ret_pct, profit=profit, days_held=pos.days_held,
            exit_reason='未平倉', peak_price=pos.peak_price,
        ))

    eq = pd.DataFrame(equity_records)
    if len(eq) == 0:
        return None, trades
    peak = eq['value'].expanding().max()
    dd = (eq['value'] - peak) / peak * 100
    max_dd = dd.min()
    total_ret = (eq['value'].iloc[-1] - cfg.capital) / cfg.capital * 100
    calmar = total_ret / abs(max_dd) if max_dd < 0 else 0

    result = PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=eq['value'].iloc[-1],
        total_return_pct=total_ret,
        max_drawdown_pct=max_dd,
        max_dd_date=eq.loc[dd.idxmin(), 'date'] if len(eq) > 0 else '',
    )
    return result, calmar


def metrics(result, calmar, label):
    """格式化輸出"""
    if result is None:
        print(f"  {label:35s} | 無資料")
        return
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    avg_win = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.return_pct for t in losses]) if losses else 0
    pr = abs(avg_win/avg_loss) if avg_loss else 0
    n_sl = sum(1 for t in closed if t.exit_reason == '停損')
    print(f"  {label:35s} | {result.total_return_pct:+7.1f}% | DD {result.max_drawdown_pct:6.1f}% "
          f"| Calmar {calmar:5.2f} | WR {wr:4.0f}% PR {pr:.1f} "
          f"| n={len(closed):3d} SL={n_sl:2d}")


# ══════════════════════════════════════════════════════════════
# 載入資料
# ══════════════════════════════════════════════════════════════
print("載入資料...")
holdings, prices = load_data()
cfg = StrategyConfig()
holdings, price_idx, special_flag = prepare_data(holdings, prices, cfg)
signals = scan_signals(holdings, price_idx, cfg, special_flag)
print(f"總訊號數: {len(signals)}")

print()
print("=" * 100)
print("  SECTION 1: MA 濾網正式測試 (全期 2022-2025)")
print("=" * 100)
print(f"  {'組合':35s} | {'總報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率盈虧比':>12} | {'交易數':>6}")
print(f"  {'─'*99}")

base_r, base_c = simulate(signals, price_idx, prices, cfg)
metrics(base_r, base_c, "基準 (無濾網)")

for ma_p in [10, 20, 30, 60]:
    r, c = simulate(signals, price_idx, prices, cfg, ma_period=ma_p)
    metrics(r, c, f"MA{ma_p} 個股濾網")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  SECTION 2: 2023 年問題解剖")
print("=" * 100)

print("\n  【2.1 逐年績效對比】")
print(f"  {'年度':35s} | {'總報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率盈虧比':>12} | {'交易數':>6}")
print(f"  {'─'*99}")

for yr in ['2022', '2023', '2024', '2025']:
    r, c = simulate(signals, price_idx, prices, cfg,
                    date_range=(f'{yr}0101', f'{yr}1231'))
    metrics(r, c, f"{yr} 年 (無濾網)")

print()
print("  【2.2 2023年 MA20 是否幫助?】")
for yr in ['2022', '2023', '2024', '2025']:
    r, c = simulate(signals, price_idx, prices, cfg, ma_period=20,
                    date_range=(f'{yr}0101', f'{yr}1231'))
    metrics(r, c, f"{yr} 年 + MA20")

# 2023年信號明細
print()
print("  【2.3 2023年所有交易明細】")
r2023, _ = simulate(signals, price_idx, prices, cfg,
                     date_range=('20230101', '20231231'))
if r2023:
    closed = [t for t in r2023.trades if t.exit_reason != '未平倉']
    print(f"  {'代碼':>6} {'買日':>10} {'賣日':>10} {'報酬':>7} {'出場':>6} {'天':>4} {'峰值%':>7}")
    for t in sorted(closed, key=lambda x: x.buy_date):
        peak_gain = (t.peak_price - t.buy_price)/t.buy_price*100
        print(f"  {t.code:>6} {t.buy_date:>10} {t.sell_date:>10} "
              f"{t.return_pct:>+6.1f}% {t.exit_reason:>5} {t.days_held:>3}d {peak_gain:>+6.1f}%峰")

# 2023 信號集中度
print()
print("  【2.4 2023年 signal 月份分布】")
sigs_2023 = [s for s in signals if '20230101' <= s.buy_date <= '20231231']
from collections import Counter
month_dist = Counter(s.buy_date[:6] for s in sigs_2023)
for m, n in sorted(month_dist.items()):
    print(f"    {m}: {n:3d} 個訊號")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  SECTION 3: Calmar > 3 策略探索")
print("=" * 100)
print(f"  {'組合':35s} | {'總報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率盈虧比':>12} | {'交易數':>6}")
print(f"  {'─'*99}")

metrics(base_r, base_c, "基準 (無任何改動)")

# A. 出場改善系列
print("\n  【A. 出場參數最佳化】")
combos_exit = [
    ("SL-5% Trail10%@10%", -5.0, 10.0, 10.0, 90),
    ("SL-6% Trail8%@12%",  -6.0, 12.0, 8.0, 90),
    ("SL-7% Trail8%@12%",  -7.0, 12.0, 8.0, 90),   # 縮緊trailing
    ("SL-7% Trail7%@10%",  -7.0, 10.0, 7.0, 90),
    ("SL-7% Trail10%@15% 60d", -7.0, 15.0, 10.0, 60),  # 縮短持有
    ("SL-7% Trail10%@15% 45d", -7.0, 15.0, 10.0, 45),
    ("SL-5% Trail10%@10% 60d", -5.0, 10.0, 10.0, 60),
]
for label, sl, ta, ts, mh in combos_exit:
    r, c = simulate(signals, price_idx, prices, cfg,
                    stop_loss=sl, trail_activate=ta, trail_stop=ts, max_hold=mh)
    metrics(r, c, label)

# B. 進場品質提升系列
print("\n  【B. 進場條件收緊】")
combos_entry = [
    ("r400>3% (更嚴)", 3.0),
    ("r400>4% (極嚴)", 4.0),
    ("r400>5% (精選)", 5.0),
]
for label, min_r in combos_entry:
    r, c = simulate(signals, price_idx, prices, cfg, min_r400=min_r)
    metrics(r, c, label)

# C. 組合改善
print("\n  【C. 組合方案 (MA20 + 出場改善)】")
combos_combo = [
    ("MA20 + SL-7% Trail8%@12%",   20, -7.0, 12.0, 8.0, 90),
    ("MA20 + SL-7% Trail7%@10%",   20, -7.0, 10.0, 7.0, 90),
    ("MA20 + SL-5% Trail10%@10%",  20, -5.0, 10.0, 10.0, 90),
    ("MA20 + SL-7% Trail8%@12% 60d", 20, -7.0, 12.0, 8.0, 60),
    ("MA20 + r400>3%",             20, -7.0, 15.0, 10.0, 90),
    ("MA30 + SL-7% Trail8%@12%",   30, -7.0, 12.0, 8.0, 90),
    ("MA60 + SL-7% Trail8%@12%",   60, -7.0, 12.0, 8.0, 90),
]
for label, ma_p, sl, ta, ts, mh in combos_combo:
    min_r4 = 3.0 if "r400>3%" in label else None
    r, c = simulate(signals, price_idx, prices, cfg,
                    ma_period=ma_p, stop_loss=sl, trail_activate=ta,
                    trail_stop=ts, max_hold=mh, min_r400=min_r4)
    metrics(r, c, label)

# D. 熔斷機制
print("\n  【D. 熔斷機制 (rolling 10筆勝率)】")
for cb_thresh in [0.25, 0.30, 0.35]:
    r, c = simulate(signals, price_idx, prices, cfg,
                    ma_period=20, circuit_breaker=cb_thresh)
    metrics(r, c, f"MA20 + 熔斷<{cb_thresh:.0%}")

# E. 找最優組合
print("\n  【E. 最優候選 (Top Calmar 搜尋)】")
best_results = []
for ma_p in [None, 20, 30]:
    for sl in [-5.0, -6.0, -7.0]:
        for ta in [10.0, 12.0, 15.0]:
            for ts in [7.0, 8.0, 10.0]:
                for mh in [45, 60, 90]:
                    if ta <= ts:
                        continue
                    r, c = simulate(signals, price_idx, prices, cfg,
                                    ma_period=ma_p, stop_loss=sl,
                                    trail_activate=ta, trail_stop=ts, max_hold=mh)
                    if r and c > 0:
                        closed = [t for t in r.trades if t.exit_reason != '未平倉']
                        if len(closed) >= 30:  # 至少30筆才有意義
                            best_results.append((c, r, ma_p, sl, ta, ts, mh))

best_results.sort(key=lambda x: -x[0])
print(f"  共測試 {len(best_results)} 組有效組合")
print()
print(f"  Top 10 最高 Calmar:")
print(f"  {'組合描述':45s} | {'總報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率':>5} | n")
for c, r, ma_p, sl, ta, ts, mh in best_results[:10]:
    closed = [t for t in r.trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    label = f"MA{ma_p or'無'} SL{sl}% T{ta}%@{ts}% {mh}d"
    print(f"  {label:45s} | {r.total_return_pct:+7.1f}% | {r.max_drawdown_pct:6.1f}% "
          f"| {c:6.2f}  | {wr:4.0f}% | {len(closed)}")

print()
print("=" * 100)
print("  分析完成")
print("=" * 100)
