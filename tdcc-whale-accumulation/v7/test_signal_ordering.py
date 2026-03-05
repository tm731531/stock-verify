"""
測試訊號排序對回測的影響
  原版：同買入日內無排序（依掃描順序）
  新版：週數少優先，同週數比 r400_chg 大的優先
"""
import sys, numpy as np, pandas as pd, datetime
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_main_engine, scan_backup_engine, V7Config,
    Position, Trade, PortfolioResult
)

print("載入資料...")
holdings, prices = load_data()
price_idx = build_price_index(prices)
cfg = V7Config()
ma_idx = build_ma_index(price_idx, cfg.backup_ma_period)

main_sigs = scan_main_engine(holdings, price_idx, cfg)
backup_sigs = scan_backup_engine(holdings, price_idx, cfg, ma_idx)

def iso_week(d):
    ts = pd.Timestamp(str(d))
    return f"{ts.year}W{ts.isocalendar()[1]:02d}"

main_iso = {iso_week(s.buy_date) for s in main_sigs}
backup_active = [s for s in backup_sigs if iso_week(s.buy_date) not in main_iso]


def simulate_with_order(main_signals, backup_signals, price_idx, prices, cfg,
                        sort_key=None):
    """
    sort_key: 同 buy_date 內主引擎訊號的排序函數
              None = 原版（不排序）
              fn   = 用 fn(signal) 排序
    """
    main_active_months = {s.buy_date[:6] for s in main_signals}
    backup_filtered = [s for s in backup_signals
                       if s.buy_date[:6] not in main_active_months]

    if sort_key:
        # 依 buy_date 分組，每組內按 sort_key 排序
        by_date = defaultdict(list)
        for s in main_signals:
            by_date[s.buy_date].append(s)
        ordered_main = []
        for d in sorted(by_date):
            ordered_main.extend(sorted(by_date[d], key=sort_key))
    else:
        ordered_main = sorted(main_signals, key=lambda s: s.buy_date)

    all_signals = sorted(
        ordered_main + backup_filtered,
        key=lambda s: (s.buy_date, 0 if s.engine == 'main' else 1)
    )

    sig_by_date = defaultdict(list)
    for s in all_signals:
        sig_by_date[s.buy_date].append(s)

    cash = cfg.capital
    positions = []
    trades = []
    held_codes = set()
    weekly_entries = defaultdict(int)
    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        new_positions = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None: new_positions.append(pos); continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_positions.append(pos); continue
            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)
            ret = (cp - pos.buy_price) / pos.buy_price * 100
            dd  = (cp - pos.peak_price) / pos.peak_price * 100
            pg  = (pos.peak_price - pos.buy_price) / pos.buy_price * 100
            reason = None
            if ret <= cfg.stop_loss_pct: reason = '停損'
            elif pg >= cfg.trailing_activate_pct and dd <= -cfg.trailing_stop_pct:
                reason = '停利' if ret > 0 else '追蹤停損'
            elif pos.days_held >= cfg.max_hold_days: reason = '到期'
            if reason:
                net = pos.shares * cp * (1 - cfg.sell_cost_rate)
                profit = net - pos.cost_basis
                cash += net
                held_codes.discard(pos.code)
                trades.append(Trade(
                    code=pos.code, engine=pos.engine,
                    buy_date=pos.buy_date, sell_date=date,
                    buy_price=pos.buy_price, sell_price=cp,
                    shares=pos.shares, return_pct=ret,
                    profit=profit, days_held=pos.days_held,
                    exit_reason=reason, peak_price=pos.peak_price,
                ))
            else:
                new_positions.append(pos)
        positions = new_positions

        if date in sig_by_date:
            _d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:]))
            _iso = _d.isocalendar()
            week_key = f'{_iso[0]}W{_iso[1]:02d}'
            for sig in sig_by_date[date]:
                if sig.code in held_codes: continue
                if len(positions) >= cfg.max_positions: continue
                if cash < cfg.per_position: continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week: continue
                shares = int(cfg.per_position / sig.buy_price)
                if shares <= 0: continue
                cost = shares * sig.buy_price * (1 + cfg.buy_fee_rate)
                if cost > cash: continue
                cash -= cost
                positions.append(Position(
                    code=sig.code, engine=sig.engine,
                    buy_date=date, buy_price=sig.buy_price,
                    shares=shares, cost_basis=cost, peak_price=sig.buy_price,
                ))
                held_codes.add(sig.code)
                weekly_entries[week_key] += 1
        pv = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                pv += pos.shares * float(parr[idx if idx < len(parr) and parr[idx,0]==date else max(0,idx-1), 1])
            else:
                pv += pos.shares * pos.buy_price
        equity_records.append({'date': date, 'value': pv})

    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret = (cp - pos.buy_price) / pos.buy_price * 100
        trades.append(Trade(
            code=pos.code, engine=pos.engine,
            buy_date=pos.buy_date, sell_date='OPEN',
            buy_price=pos.buy_price, sell_price=cp,
            shares=pos.shares, return_pct=ret,
            profit=pos.shares * cp - pos.cost_basis,
            days_held=pos.days_held, exit_reason='未平倉',
            peak_price=pos.peak_price,
        ))

    eq = pd.DataFrame(equity_records)
    peak = eq['value'].expanding().max()
    dd_s = (eq['value'] - peak) / peak * 100
    max_dd = dd_s.min()
    return PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=eq['value'].iloc[-1],
        total_return_pct=(eq['value'].iloc[-1] - cfg.capital) / cfg.capital * 100,
        max_drawdown_pct=max_dd,
        max_dd_date=eq.loc[dd_s.idxmin(), 'date'] if len(eq) > 0 else '',
    )


def show(result, label):
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    main_t = [t for t in closed if t.engine == 'main']
    wins   = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0
    wr = len(wins)/len(closed)*100 if closed else 0
    print(f"\n  【{label}】")
    print(f"  ├ 總報酬: {result.total_return_pct:>+7.1f}%  最大回撤: {result.max_drawdown_pct:>6.1f}%  Calmar: {calmar:>6.2f}")
    print(f"  ├ 已平倉: {len(closed)}筆  勝率: {wr:.0f}%  均贏: {np.mean([t.return_pct for t in wins]):+.1f}%  均虧: {np.mean([t.return_pct for t in losses]):+.1f}%")
    print(f"  ├ 逐年: ", end='')
    for yr in ['2022','2023','2024','2025']:
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        print(f"{yr}:{sum(t.profit for t in yr_t):>+8,.0f}  ", end='')
    print()
    # 看主引擎的週數分布
    from strategy_v7 import Signal
    sig_map = {(s.code, s.buy_date): s for s in main_sigs}
    streak_dist = defaultdict(int)
    for t in main_t:
        sig = sig_map.get((t.code, t.buy_date))
        if sig:
            g = str(sig.streak) if sig.streak <= 5 else ('6-7' if sig.streak <= 7 else '8+')
            streak_dist[g] += 1
    print(f"  └ 主引擎週數分布: {dict(sorted(streak_dist.items()))}")
    return calmar


print()
print("=" * 70)
print("  訊號排序對回測的影響")
print("=" * 70)

# 原版（無明確排序）
r1 = simulate_with_order(main_sigs, backup_active, price_idx, prices, cfg,
                         sort_key=None)
c1 = show(r1, "原版（買入日內無排序）")

# 新版：週數少優先，同週數 r400_chg 大優先
r2 = simulate_with_order(main_sigs, backup_active, price_idx, prices, cfg,
                         sort_key=lambda s: (s.streak, -s.r400_chg))
c2 = show(r2, "新版（週數少優先 → r400_chg 大優先）")

# 純比例（原本的通知排序）
r3 = simulate_with_order(main_sigs, backup_active, price_idx, prices, cfg,
                         sort_key=lambda s: -s.r400_chg)
c3 = show(r3, "比較：純 r400_chg 優先")

print()
print("=" * 70)
diff = c2 - c1
arrow = "↑" if diff > 0 else "↓"
print(f"  原版  Calmar: {c1:.2f}")
print(f"  新版  Calmar: {c2:.2f}  {arrow} {abs(diff):.2f}")
print(f"  純比例 Calmar: {c3:.2f}")
