"""
v7.1 + 減半倉規則測試

規則：同一支股票在同一年度曾經停損過，
      下次再觸發訊號時，倉位減半（125,000 → 62,500）

目的：
  - 用資料回答「這個規則有沒有用」
  - 比較 v7.1 原版 vs v7.1+減半 的 Calmar
  - 同時也跟 v7.2（延遲2天，無減半）比較
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_backup_engine, V7Config, Signal,
    Position, Trade, PortfolioResult,
)

# ── 資料載入 ─────────────────────────────────────────────────────
print("載入資料...")
holdings, prices = load_data()
price_idx = build_price_index(prices)
ma_idx    = build_ma_index(price_idx, 20)


# ── v7.1 主引擎（延遲3天）──────────────────────────────────────

def scan_main_v71(holdings, price_idx, cfg):
    """v7.1 主引擎：延遲3天入場"""
    signals = []
    for code, grp in holdings.groupby('stock_code'):
        grp = grp.sort_values('date')
        dates   = grp['date'].values
        r400    = grp['ratio_400_above'].values.astype(float)
        r1000   = grp['ratio_1000_above'].values.astype(float)
        holders = grp['total_holders'].values.astype(float)

        for i in range(1, len(dates)):
            streak = 0
            for j in range(i, 0, -1):
                if r400[j] > r400[j-1]: streak += 1
                else: break
            if streak < cfg.min_streak: continue

            si = i - streak
            r400_chg = r400[i] - r400[si]
            r1000_chg = r1000[i] - r1000[si]
            sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
            h_chg = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

            if r400_chg < cfg.min_r400_chg: continue
            if sync < cfg.min_sync: continue
            if h_chg > cfg.max_holder_chg: continue
            if code not in price_idx: continue

            parr = price_idx[code]
            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr): continue
            price = float(parr[pi, 1])
            if price < cfg.min_price_main: continue

            # 延遲3天 + 收盤+3%限價 + 5天窗口
            after = parr[parr[:, 0] > dates[i]]
            if len(after) < 4: continue
            limit = price * 1.03
            window = after[3:8]
            for k in range(len(window)):
                if float(window[k, 1]) <= limit:
                    signals.append(Signal(
                        code=code, engine='main',
                        signal_date=dates[i],
                        buy_date=window[k, 0],
                        buy_price=min(limit, float(window[k, 1])),
                        streak=streak, r400_chg=r400_chg,
                        sync=sync, holder_chg_pct=h_chg,
                    ))
                    break

    return sorted(signals, key=lambda s: s.buy_date)


# ── 模擬引擎（加入減半倉規則）───────────────────────────────────

def simulate_with_halfpos(main_signals, backup_signals, price_idx, prices, cfg,
                          use_halfpos=False):
    """
    use_halfpos=True：同股同年停損後，下次倉位減半
    use_halfpos=False：標準 v7.1 邏輯（不改變倉位）
    """
    main_active_months = {s.buy_date[:6] for s in main_signals}
    backup_filtered = [s for s in backup_signals
                       if s.buy_date[:6] not in main_active_months]

    all_signals = sorted(
        main_signals + backup_filtered,
        key=lambda s: (s.buy_date, 0 if s.engine == 'main' else 1)
    )

    sig_by_date = defaultdict(list)
    for s in all_signals:
        sig_by_date[s.buy_date].append(s)

    cash = cfg.capital
    positions: list[Position] = []
    trades: list[Trade] = []
    held_codes: set[str] = set()
    weekly_entries: dict[str, int] = defaultdict(int)

    # 追蹤各股各年度是否停損過
    # key: (code, year) → True/False
    stoploss_memory: set[tuple] = set()

    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        # 出場
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
            if ret <= cfg.stop_loss_pct:
                reason = '停損'
            elif pg >= cfg.trailing_activate_pct and dd <= -cfg.trailing_stop_pct:
                reason = '停利' if ret > 0 else '追蹤停損'
            elif pos.days_held >= cfg.max_hold_days:
                reason = '到期'

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
                # 記錄停損
                if use_halfpos and reason == '停損':
                    year = pos.buy_date[:4]
                    stoploss_memory.add((pos.code, year))
            else:
                new_positions.append(pos)
        positions = new_positions

        # 進場
        if date in sig_by_date:
            week_key = date[:6]
            for sig in sig_by_date[date]:
                if sig.code in held_codes: continue
                if len(positions) >= cfg.max_positions: continue
                if cash < cfg.per_position * 0.5: continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week: continue

                # 決定倉位大小
                if use_halfpos:
                    year = sig.buy_date[:4]
                    if (sig.code, year) in stoploss_memory:
                        pos_size = cfg.per_position * 0.5  # 減半
                        is_half = True
                    else:
                        pos_size = cfg.per_position
                        is_half = False
                else:
                    pos_size = cfg.per_position
                    is_half = False

                if cash < pos_size: continue
                shares = int(pos_size / sig.buy_price)
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

        # 淨值
        pv = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                pv += pos.shares * float(parr[idx if idx < len(parr) and parr[idx,0]==date else max(0,idx-1), 1])
            else:
                pv += pos.shares * pos.buy_price
        equity_records.append({'date': date, 'value': pv, 'n_positions': len(positions)})

    # 結算未平倉
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


# ── 顯示結果 ────────────────────────────────────────────────────

def show(result, label, cfg):
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    main_t = [t for t in closed if t.engine == 'main']
    wins   = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr     = len(wins)/len(closed)*100 if closed else 0
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0

    # 找出被減半的交易
    sl_affected = []
    stoploss_codes = set()
    for t in sorted(closed, key=lambda x: x.buy_date):
        key = (t.code, t.buy_date[:4])
        if t.exit_reason == '停損':
            stoploss_codes.add(key)
        elif key in stoploss_codes:
            sl_affected.append(t)

    print(f"\n  【{label}】")
    print(f"  ├ 總報酬: {result.total_return_pct:>+7.1f}%  最大回撤: {result.max_drawdown_pct:>6.1f}%  Calmar: {calmar:>6.2f}")
    print(f"  ├ 已平倉: {len(closed)}筆  勝率: {wr:.0f}%  均贏: {np.mean([t.return_pct for t in wins]):+.1f}%  均虧: {np.mean([t.return_pct for t in losses]):+.1f}%")
    print(f"  ├ 逐年: ", end='')
    for yr in ['2022','2023','2024','2025']:
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        pnl  = sum(t.profit for t in yr_t)
        print(f"{yr}:{pnl:>+8,.0f}  ", end='')
    print()
    if sl_affected:
        print(f"  └ 減半倉觸發: {len(sl_affected)}筆 → {', '.join(set(t.code for t in sl_affected))}")
    else:
        print(f"  └ 減半倉觸發: 無")
    return calmar


# ── 主流程 ──────────────────────────────────────────────────────

print()
print("=" * 80)
print("  v7.1（延遲3天）+ 減半倉規則測試")
print("=" * 80)

cfg = V7Config()

# 掃描訊號（v7.1：延遲3天）
main_sigs = scan_main_v71(holdings, price_idx, cfg)

def iso_week(d):
    ts = pd.Timestamp(str(d))
    return f"{ts.year}W{ts.isocalendar()[1]:02d}"

main_iso = {iso_week(s.buy_date) for s in main_sigs}
backup_pre = [s for s in scan_backup_engine(holdings, price_idx, cfg, ma_idx)
              if iso_week(s.buy_date) not in main_iso]

print(f"\n  主引擎訊號: {len(main_sigs)} 筆")
print(f"  補位訊號（ISO週過濾後）: {len(backup_pre)} 筆")
print()

# 情境A：v7.1 原版（無減半）
r_base = simulate_with_halfpos(main_sigs, backup_pre, price_idx, prices, cfg, use_halfpos=False)
calmar_base = show(r_base, "v7.1 原版（無減半）", cfg)

# 情境B：v7.1 + 減半倉
r_half = simulate_with_halfpos(main_sigs, backup_pre, price_idx, prices, cfg, use_halfpos=True)
calmar_half = show(r_half, "v7.1 + 同股同年停損後減半倉", cfg)

# 比較
print()
print("=" * 80)
print("  對比摘要")
print("=" * 80)
diff = calmar_half - calmar_base
arrow = "↑" if diff > 0 else "↓"
print(f"  v7.1 原版:   Calmar {calmar_base:>6.2f}")
print(f"  v7.1+減半:   Calmar {calmar_half:>6.2f}  {arrow} {abs(diff):.2f}")
print()

if diff > 0.5:
    print("  結論：減半倉規則有效降低回撤，Calmar 顯著提升，建議採用")
elif diff > 0:
    print("  結論：減半倉規則略有改善，但效果有限，視個人風險偏好決定")
elif diff > -0.5:
    print("  結論：減半倉規則效果中性，與原版差異不大")
else:
    print("  結論：減半倉規則讓 Calmar 下降，主要原因可能是：")
    print("        減少了部分後來獲利的交易倉位，總報酬下滑幅度 > 回撤降低幅度")

print()
print("  ※ 另作參考：v7.2（延遲2天，無減半）Calmar = 16.38")
print("     → 若 v7.1+減半 > 10.41（v7.1 原版），可考慮兩者結合")
