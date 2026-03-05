"""
策略組合測試：
問題：無法預知何時用哪個策略
解法選項：
  1. 直接雙策略同時跑（共享資金池）
  2. 用近期績效自動切換
  3. 永遠用 v6d，B策略只做補位（v6d 沒訊號時才用 B）
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from explore_strategies import backtest, Pos, Trd
from strategy_v6d import load_data, prepare_data, scan_signals, StrategyConfig

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

# ── 載入資料 ─────────────────────────────────────────────────
print("載入資料...")
conn = sqlite3.connect(DB_PATH)
prices_df = pd.read_sql(
    "SELECT stock_code, date, close_price FROM daily_prices ORDER BY stock_code, date", conn)
holdings_df = pd.read_sql(
    "SELECT * FROM holdings ORDER BY stock_code, date", conn)
conn.close()

price_idx = {}
for code, grp in prices_df.groupby('stock_code'):
    price_idx[code] = grp.sort_values('date')[['date', 'close_price']].values

ma_idx = {}
for code, parr in price_idx.items():
    closes = pd.Series(parr[:, 1].astype(float))
    ma_idx[code] = closes.rolling(20).mean().values

all_dates = sorted(prices_df['date'].unique())

# ── 產生 B 訊號 ───────────────────────────────────────────────
def gen_b_signals(flee_pct=-5.0, lookback=4, min_price=50, delay=5):
    sigs = defaultdict(list)
    for code, grp in holdings_df.groupby('stock_code'):
        if code.startswith('00'): continue
        grp = grp.sort_values('date').reset_index(drop=True)
        if len(grp) < lookback + 1 or code not in price_idx: continue
        parr = price_idx[code]
        ma20 = ma_idx[code]
        holders = grp['total_holders'].values
        dates = grp['date'].values
        for i in range(lookback, len(dates)):
            h_now, h_bef = holders[i], holders[i - lookback]
            if h_bef <= 0: continue
            flee = (h_now - h_bef) / h_bef * 100
            if flee > flee_pct: continue
            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr): continue
            cp = float(parr[pi, 1])
            if cp < min_price: continue
            if np.isnan(ma20[pi]) or cp < ma20[pi]: continue
            if pi + delay >= len(parr): continue
            buy_date = parr[pi + delay, 0]
            buy_price = float(parr[pi + delay, 1])
            if buy_price <= 0: continue
            sigs[buy_date].append((code, buy_price))
    return sigs

# ── 產生 v6d 訊號 ──────────────────────────────────────────────
print("產生訊號...")
holdings_v6, prices_v6 = load_data()
cfg = StrategyConfig()
h_v6, pidx_v6, sf = prepare_data(holdings_v6, prices_v6, cfg)
sigs_v6_list = scan_signals(h_v6, pidx_v6, cfg, sf)
sigs_v6 = defaultdict(list)
for s in sigs_v6_list:
    sigs_v6[s.buy_date].append((s.code, s.buy_price))

sigs_b = gen_b_signals()

# 把 v6d 的訊號標記來源
sigs_v6_tagged = {d: [('v6d', c, p) for c, p in v] for d, v in sigs_v6.items()}
sigs_b_tagged  = {d: [('b',   c, p) for c, p in v] for d, v in sigs_b.items()}

print(f"v6d 訊號: {sum(len(v) for v in sigs_v6.values())} 筆")
print(f"B 訊號:   {sum(len(v) for v in sigs_b.values())} 筆")

# ══════════════════════════════════════════════════════════════
# 通用回測核心（支援優先順序）
# ══════════════════════════════════════════════════════════════
def backtest_combo(primary_sigs, secondary_sigs=None,
                   capital=500_000, per_position=125_000,
                   max_pos=4, max_per_week=2,
                   stop_loss=-7.0, trail_activate=15.0,
                   trail_stop=10.0, max_hold=90,
                   date_range=None,
                   adaptive_switch=False):
    """
    primary_sigs: 優先使用的策略訊號
    secondary_sigs: 補位策略（primary 沒訊號才用）
    adaptive_switch: 是否根據近期績效自動選擇
    """
    if date_range:
        s, e = date_range
        work_dates = [d for d in all_dates if s <= d <= e]
    else:
        work_dates = all_dates

    cash = capital
    positions = []
    trades = []
    held = set()
    week_cnt = defaultdict(int)
    eq = []
    recent_pnl = {'v6d': [], 'b': []}  # 近期績效追蹤

    for date in work_dates:
        # 出場
        new_pos = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None: new_pos.append(pos); continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_pos.append(pos); continue

            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)
            ret = (cp - pos.buy_price) / pos.buy_price * 100
            dd  = (cp - pos.peak_price) / pos.peak_price * 100
            pg  = (pos.peak_price - pos.buy_price) / pos.buy_price * 100

            reason = None
            if ret <= stop_loss: reason = '停損'
            elif pg >= trail_activate and dd <= -trail_stop: reason = '停利'
            elif pos.days_held >= max_hold: reason = '到期'

            if reason:
                net = pos.shares * cp * (1 - 0.004425)
                profit = net - pos.cost_basis
                cash += net
                held.discard(pos.code)
                trades.append(Trd(pos.code, pos.buy_date, date,
                                  pos.buy_price, cp, ret, profit,
                                  pos.days_held, reason))
                tag = getattr(pos, 'tag', 'unknown')
                recent_pnl.get(tag, []).append(1 if profit > 0 else 0)
            else:
                new_pos.append(pos)
        positions = new_pos

        # 進場：決定今天用哪個策略
        week_key = date[:6]
        candidates = []

        if adaptive_switch and len(recent_pnl['v6d']) >= 5 and len(recent_pnl['b']) >= 5:
            # 根據近10筆勝率決定優先
            wr_v6d = sum(recent_pnl['v6d'][-10:]) / min(10, len(recent_pnl['v6d']))
            wr_b   = sum(recent_pnl['b'][-10:])   / min(10, len(recent_pnl['b']))
            if wr_v6d >= wr_b:
                today_primary, today_secondary = primary_sigs, secondary_sigs
            else:
                today_primary, today_secondary = secondary_sigs, primary_sigs
        else:
            today_primary, today_secondary = primary_sigs, secondary_sigs

        # 先加入 primary 訊號
        if date in today_primary:
            for tag, code, bp in today_primary[date]:
                candidates.append((tag, code, bp, 0))  # priority 0 = primary

        # 再加入 secondary（補位）
        if today_secondary and date in today_secondary:
            for tag, code, bp in today_secondary[date]:
                candidates.append((tag, code, bp, 1))  # priority 1 = secondary

        # 依優先順序排序，primary 先
        candidates.sort(key=lambda x: x[3])

        for tag, code, bp, prio in candidates:
            if code in held or len(positions) >= max_pos: continue
            if cash < per_position: continue
            if week_cnt[week_key] >= max_per_week: continue
            if bp <= 0: continue
            shares = int(per_position / bp)
            if shares <= 0: continue
            cost = shares * bp * 1.001425
            if cost > cash: continue
            cash -= cost
            p = Pos(code, date, bp, shares, cost, bp)
            p.tag = tag
            positions.append(p)
            held.add(code)
            week_cnt[week_key] += 1

        # 計算淨值
        pv = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                if idx < len(parr) and parr[idx, 0] == date:
                    pv += pos.shares * float(parr[idx, 1])
                else:
                    pv += pos.shares * pos.buy_price
            else:
                pv += pos.shares * pos.buy_price
        eq.append({'date': date, 'value': pv})

    # 結算
    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret = (cp - pos.buy_price) / pos.buy_price * 100
        trades.append(Trd(pos.code, pos.buy_date, 'OPEN',
                          pos.buy_price, cp, ret,
                          pos.shares * cp - pos.cost_basis,
                          pos.days_held, '未平倉'))

    df = pd.DataFrame(eq)
    if len(df) == 0: return None
    peak = df['value'].expanding().max()
    dd_s = (df['value'] - peak) / peak * 100
    max_dd = dd_s.min()
    total_ret = (df['value'].iloc[-1] - capital) / capital * 100
    calmar = total_ret / abs(max_dd) if max_dd < 0 else 0
    closed = [t for t in trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    pr = abs(np.mean([t.return_pct for t in wins])/
             np.mean([t.return_pct for t in losses])) if losses and wins else 0
    n_sl = sum(1 for t in closed if t.exit_reason == '停損')
    return dict(ret=total_ret, dd=max_dd, calmar=calmar,
                wr=wr, pr=pr, n=len(closed), n_sl=n_sl, trades=trades)


def show(label, m, width=45):
    if m is None: print(f"  {label:{width}} | 無資料"); return
    print(f"  {label:{width}} | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
          f"| Calmar {m['calmar']:>5.2f} | WR {m['wr']:>4.0f}% PR {m['pr']:.1f} "
          f"| n={m['n']:>3d} SL={m['n_sl']}")


# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  各策略單獨跑（基準）")
print("=" * 100)
print(f"  {'方案':45s} | {'報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率PR':>9} | n SL")
print(f"  {'─'*98}")

m_v6d = backtest(sigs_v6, price_idx, all_dates)
show("原始 v6d（大戶連升）", m_v6d)

m_b = backtest(sigs_b, price_idx, all_dates)
show("策略 B（散戶出逃）", m_b)

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  方案一：直接雙策略同時跑（共享 4 個倉位名額）")
print("=" * 100)
print("  [說明] v6d 和 B 訊號同等優先，誰先觸發就用誰，共用 4 倉 500k")
print()

# 合併訊號（v6d 優先）
m_both_v6d_first = backtest_combo(sigs_v6_tagged, sigs_b_tagged)
show("雙策略 (v6d優先)", m_both_v6d_first)

m_both_b_first = backtest_combo(sigs_b_tagged, sigs_v6_tagged)
show("雙策略 (B優先)", m_both_b_first)

# 逐年
print()
print("  逐年績效（v6d優先組合）：")
for yr in ['2022', '2023', '2024', '2025']:
    m_yr = backtest_combo(sigs_v6_tagged, sigs_b_tagged,
                          date_range=(f'{yr}0101', f'{yr}1231'))
    if m_yr:
        print(f"    {yr}: 報酬 {m_yr['ret']:>+7.1f}% | DD {m_yr['dd']:>6.1f}% "
              f"| Calmar {m_yr['calmar']:>5.2f} | WR {m_yr['wr']:>4.0f}% | n={m_yr['n']}")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  方案二：v6d 主策略，B 策略補位（v6d 沒有訊號的週才讓 B 進場）")
print("=" * 100)
print("  [說明] 有 v6d 訊號的週，B 策略禁止進場；沒有 v6d 訊號才讓 B 補")
print()

# 找有 v6d 訊號的週
v6d_active_weeks = set()
for date in sigs_v6.keys():
    v6d_active_weeks.add(date[:6])

# B 訊號只在 v6d 靜默的週才啟用
sigs_b_backup = defaultdict(list)
for date, entries in sigs_b_tagged.items():
    if date[:6] not in v6d_active_weeks:
        sigs_b_backup[date] = entries

print(f"  v6d 有訊號的月份數: {len(v6d_active_weeks)}")
print(f"  B 可補位訊號數: {sum(len(v) for v in sigs_b_backup.values())}")
print()

m_backup = backtest_combo(sigs_v6_tagged, sigs_b_backup)
show("v6d主 + B補位", m_backup)

for yr in ['2022', '2023', '2024', '2025']:
    m_yr = backtest_combo(sigs_v6_tagged, sigs_b_backup,
                          date_range=(f'{yr}0101', f'{yr}1231'))
    if m_yr:
        print(f"    {yr}: 報酬 {m_yr['ret']:>+7.1f}% | DD {m_yr['dd']:>6.1f}% "
              f"| Calmar {m_yr['calmar']:>5.2f} | WR {m_yr['wr']:>4.0f}% | n={m_yr['n']}")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  方案三：根據近期績效自動切換（哪個最近贏率高就優先用哪個）")
print("=" * 100)
print("  [說明] 滾動最近10筆，哪個策略勝率高就優先排序")
print()

m_adaptive = backtest_combo(sigs_v6_tagged, sigs_b_tagged, adaptive_switch=True)
show("自適應切換", m_adaptive)

for yr in ['2022', '2023', '2024', '2025']:
    m_yr = backtest_combo(sigs_v6_tagged, sigs_b_tagged, adaptive_switch=True,
                          date_range=(f'{yr}0101', f'{yr}1231'))
    if m_yr:
        print(f"    {yr}: 報酬 {m_yr['ret']:>+7.1f}% | DD {m_yr['dd']:>6.1f}% "
              f"| Calmar {m_yr['calmar']:>5.2f} | WR {m_yr['wr']:>4.0f}% | n={m_yr['n']}")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  方案四：增加總倉位（8倉，兩策略各用4倉，資金各250k）")
print("=" * 100)
print("  [說明] 擴大資金池到 100萬，兩個策略各自跑各自的 4 倉")
print()

m_8pos = backtest_combo(sigs_v6_tagged, sigs_b_tagged,
                        capital=1_000_000, per_position=125_000, max_pos=8,
                        max_per_week=4)
show("雙策略 8倉 100萬", m_8pos)

for yr in ['2022', '2023', '2024', '2025']:
    m_yr = backtest_combo(sigs_v6_tagged, sigs_b_tagged,
                          capital=1_000_000, per_position=125_000,
                          max_pos=8, max_per_week=4,
                          date_range=(f'{yr}0101', f'{yr}1231'))
    if m_yr:
        pct = m_yr['ret']
        print(f"    {yr}: 報酬 {pct:>+7.1f}% | DD {m_yr['dd']:>6.1f}% "
              f"| Calmar {m_yr['calmar']:>5.2f} | WR {m_yr['wr']:>4.0f}% | n={m_yr['n']}")

# ══════════════════════════════════════════════════════════════
print()
print("=" * 100)
print("  總結對比")
print("=" * 100)
print(f"  {'方案':45s} | {'報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率':>5} | n")
show("v6d 單獨", m_v6d)
show("B 單獨", m_b)
show("方案一：雙策略同時（v6d優先）", m_both_v6d_first)
show("方案二：v6d主 + B補位", m_backup)
show("方案三：自適應切換", m_adaptive)
show("方案四：8倉雙策略 100萬", m_8pos)
