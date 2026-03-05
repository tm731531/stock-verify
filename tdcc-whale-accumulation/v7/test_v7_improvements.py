"""
v7.1 四項改進測試
  改進一：股票冷卻期（補位引擎停損後 90 天不再觸發同一股票）
  改進二：補位縮半倉（補位每筆 6.25 萬而非 12.5 萬）
  改進三：大盤濾網（TAIEX 低於 MA60 時，補位引擎暫停）
  改進四（組合）：一 + 二 + 三 全部啟用
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_main_engine, scan_backup_engine,
    V7Config, Signal, Position, Trade, PortfolioResult
)

print("載入資料...")
holdings, prices = load_data()
price_idx = build_price_index(prices)
ma_idx    = build_ma_index(price_idx, 20)

# ── 載入大盤資料 ──────────────────────────────────────────────
taiex_df = pd.read_csv(Path(__file__).parent.parent / 'data' / 'taiex.csv')
taiex_df['date'] = taiex_df['date'].astype(str).str.replace('-', '')
taiex_df = taiex_df.sort_values('date').reset_index(drop=True)
taiex_df['ma60'] = taiex_df['taiex'].rolling(60).mean()
taiex_map = dict(zip(taiex_df['date'], taiex_df['taiex']))
taiex_ma60_map = dict(zip(taiex_df['date'], taiex_df['ma60']))


def get_taiex_above_ma60(date_str: str) -> bool:
    """當日大盤是否站上 MA60（往前找最近有效日）"""
    dates_sorted = sorted(taiex_map.keys())
    idx = np.searchsorted(dates_sorted, date_str)
    idx = min(idx, len(dates_sorted) - 1)
    d = dates_sorted[idx] if dates_sorted[idx] == date_str else (
        dates_sorted[idx - 1] if idx > 0 else None
    )
    if d is None:
        return True
    taiex_val = taiex_map.get(d)
    ma60_val  = taiex_ma60_map.get(d)
    if taiex_val is None or ma60_val is None or pd.isna(ma60_val):
        return True
    return taiex_val >= ma60_val


# ── 改良版 simulate（支援冷卻期 + 縮半倉 + 大盤濾網）──────────
def simulate_improved(
    main_signals: list,
    backup_signals: list,
    price_idx: dict,
    prices,
    cfg: V7Config,
    cooldown_days: int = 0,        # 改進一：冷卻期天數（0=關閉）
    backup_half_position: bool = False,  # 改進二：補位縮半倉
    market_filter: bool = False,   # 改進三：大盤濾網
) -> PortfolioResult:

    # ── 大盤濾網：預先過濾補位訊號 ────────────────────────────
    if market_filter:
        backup_signals = [s for s in backup_signals
                          if get_taiex_above_ma60(s.buy_date)]

    # ── 月份二次過濾（與 v7.1 一致）──────────────────────────
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
    positions: list = []
    trades: list = []
    held_codes: set = set()
    weekly_entries = defaultdict(int)

    # 改進一：記錄補位引擎停損時間
    backup_stop_dates: dict[str, str] = {}   # code → 最近一次補位停損日

    # 補位每倉金額
    backup_per_pos = cfg.per_position * 0.5 if backup_half_position else cfg.per_position

    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        # ── 出場 ───────────────────────────────────────────────
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
                # 改進一：記錄補位停損日
                if reason == '停損' and pos.engine == 'backup':
                    backup_stop_dates[pos.code] = date

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

        # ── 進場 ───────────────────────────────────────────────
        if date in sig_by_date:
            week_key = date[:6]
            for sig in sig_by_date[date]:
                if sig.code in held_codes: continue
                if len(positions) >= cfg.max_positions: continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week: continue

                # 決定本倉金額
                per_pos = backup_per_pos if sig.engine == 'backup' else cfg.per_position

                if cash < per_pos: continue

                # 改進一：冷卻期檢查
                if cooldown_days > 0 and sig.engine == 'backup':
                    last_stop = backup_stop_dates.get(sig.code)
                    if last_stop is not None:
                        days_since = (pd.Timestamp(date) - pd.Timestamp(last_stop)).days
                        if days_since < cooldown_days:
                            continue

                shares = int(per_pos / sig.buy_price)
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

        # ── 淨值 ───────────────────────────────────────────────
        pv = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                i2 = np.searchsorted(parr[:, 0], date)
                pv += pos.shares * float(parr[
                    i2 if i2 < len(parr) and parr[i2, 0] == date else max(0, i2 - 1), 1
                ])
            else:
                pv += pos.shares * pos.buy_price
        equity_records.append({'date': date, 'equity': pv})

    # ── 未平倉 ────────────────────────────────────────────────
    for pos in positions:
        parr = price_idx.get(pos.code)
        last_date = all_trade_dates[-1] if all_trade_dates else date
        if parr is not None:
            last_p = float(parr[-1, 1])
        else:
            last_p = pos.buy_price
        ret = (last_p - pos.buy_price) / pos.buy_price * 100
        profit = pos.shares * last_p * (1 - cfg.sell_cost_rate) - pos.cost_basis
        trades.append(Trade(
            code=pos.code, engine=pos.engine,
            buy_date=pos.buy_date, sell_date='OPEN',
            buy_price=pos.buy_price, sell_price=last_p,
            shares=pos.shares, return_pct=ret,
            profit=profit, days_held=pos.days_held,
            exit_reason='未平倉', peak_price=pos.peak_price,
        ))

    eq = pd.DataFrame(equity_records)
    final_val = eq['equity'].iloc[-1] if not eq.empty else cfg.capital
    total_ret = (final_val - cfg.capital) / cfg.capital * 100
    roll_max = eq['equity'].cummax()
    dd_series = (eq['equity'] - roll_max) / roll_max * 100
    max_dd = float(dd_series.min())
    max_dd_date = eq.loc[dd_series.idxmin(), 'date'] if not dd_series.empty else ''

    return PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=final_val, total_return_pct=total_ret,
        max_drawdown_pct=max_dd, max_dd_date=max_dd_date,
    )


# ── 統一跑法 ──────────────────────────────────────────────────
def run(label, cooldown=0, half_pos=False, mkt_filter=False):
    cfg = V7Config()

    # 取得 ISO 週過濾後的補位訊號（與 v7.1 一致）
    main_sigs   = scan_main_engine(holdings, price_idx, cfg)
    backup_sigs = scan_backup_engine(holdings, price_idx, cfg, ma_idx)

    def iso_week(d):
        ts = pd.Timestamp(str(d))
        return f"{ts.year}W{ts.isocalendar()[1]:02d}"

    main_iso = {iso_week(s.buy_date) for s in main_sigs}
    backup_pre = [s for s in backup_sigs if iso_week(s.buy_date) not in main_iso]

    result = simulate_improved(
        main_sigs, backup_pre, price_idx, prices, cfg,
        cooldown_days=cooldown,
        backup_half_position=half_pos,
        market_filter=mkt_filter,
    )

    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    wins   = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr     = len(wins) / len(closed) * 100 if closed else 0
    avg_w  = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_l  = np.mean([t.return_pct for t in losses]) if losses else 0
    pr     = abs(avg_w / avg_l) if avg_l else 0
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0
    n_sl   = sum(1 for t in closed if t.exit_reason == '停損')
    backup_t = [t for t in closed if t.engine == 'backup']
    main_t   = [t for t in closed if t.engine == 'main']
    backup_sl = sum(1 for t in backup_t if t.exit_reason == '停損')

    print(f"\n  {'─'*85}")
    print(f"  {label}")
    print(f"  {'─'*85}")
    print(f"  報酬: {result.total_return_pct:>+7.1f}%  |  最大回撤: {result.max_drawdown_pct:>6.1f}%  |  Calmar: {calmar:>5.2f}")
    print(f"  勝率: {wr:>4.0f}%  |  盈虧比: {pr:.1f}  |  n={len(closed)}(停損{n_sl})")
    print(f"  主引擎: {len(main_t)}筆  |  補位: {len(backup_t)}筆(停損{backup_sl})")
    print(f"  逐年: ", end='')
    for yr in ['2022', '2023', '2024', '2025']:
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        yr_w = sum(1 for t in yr_t if t.profit > 0)
        yr_pnl = sum(t.profit for t in yr_t)
        print(f"{yr}:{yr_pnl:>+8,.0f}({yr_w}/{len(yr_t)})  ", end='')
    print()
    return calmar, result


print()
print("=" * 90)
print("  v7.1 改進項目測試")
print("=" * 90)

c0, r0 = run("基準 v7.1（無改進）")
c1, r1 = run("改進一：冷卻期 90 天",                   cooldown=90)
c2, r2 = run("改進二：補位縮半倉（6.25萬）",            half_pos=True)
c3, r3 = run("改進三：大盤濾網（TAIEX≥MA60）",          mkt_filter=True)
c4, r4 = run("改進一+二：冷卻期 + 縮半倉",              cooldown=90, half_pos=True)
c5, r5 = run("改進一+三：冷卻期 + 大盤濾網",            cooldown=90, mkt_filter=True)
c6, r6 = run("改進二+三：縮半倉 + 大盤濾網",            half_pos=True, mkt_filter=True)
c7, r7 = run("全部改進（冷卻期+縮半倉+大盤濾網）",       cooldown=90, half_pos=True, mkt_filter=True)

print()
print("=" * 90)
print("  Calmar 對比總覽")
print("=" * 90)
results = [
    ("基準 v7.1", c0),
    ("改進一：冷卻期", c1),
    ("改進二：縮半倉", c2),
    ("改進三：大盤濾網", c3),
    ("改進一+二", c4),
    ("改進一+三", c5),
    ("改進二+三", c6),
    ("全部改進", c7),
]
for label, c in results:
    bar  = '█' * int(c * 2) if c > 0 else ''
    flag = '✅' if c >= 3 else '⚠️'
    chg  = c - c0
    sign = '+' if chg >= 0 else ''
    print(f"  {flag} {label:35s}  Calmar {c:>5.2f}  ({sign}{chg:+.2f})  {bar}")
