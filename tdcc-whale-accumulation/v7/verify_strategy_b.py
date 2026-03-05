"""
策略B 深度驗證：散戶出逃 + 股價站上 MA20
1. 逐筆交易明細（確認沒有邏輯問題）
2. 前瞻偏差檢查（TDCC 資料公布時間）
3. Out-of-sample 驗證 (2022-2023 訓練 / 2024-2025 測試)
4. 逐年績效
5. 敏感度測試（參數稍微改動結果會不會崩潰）
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

DB_PATH = Path(__file__).parent.parent / 'data' / 'tdcc_holdings.db'

# ── 載入資料 ──────────────────────────────────────────────────
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
    ma_idx[code] = {
        20: closes.rolling(20).mean().values,
        60: closes.rolling(60).mean().values,
    }

all_dates = sorted(prices_df['date'].unique())
print(f"股票: {len(price_idx)}  交易日: {len(all_dates)}")


# ══════════════════════════════════════════════════════════════
# 策略B 訊號產生（清楚版本，方便檢查）
# ══════════════════════════════════════════════════════════════
def gen_b_signals(flee_pct_thresh=-5.0, lookback_weeks=4,
                  min_price=50, require_ma20=True,
                  delay_days=5):
    """
    flee_pct_thresh: 持有人4週下降超過此值才觸發 (e.g. -5 = 下降5%)
    delay_days: TDCC 資料公布後幾天買入 (預設5天 = 下週)
    """
    sigs = defaultdict(list)
    sig_details = []  # 存訊號明細

    for code, grp in holdings_df.groupby('stock_code'):
        if code.startswith('00'):
            continue
        grp = grp.sort_values('date').reset_index(drop=True)
        if len(grp) < lookback_weeks + 1 or code not in price_idx:
            continue

        parr = price_idx[code]
        ma20 = ma_idx[code][20]
        holders = grp['total_holders'].values
        dates = grp['date'].values

        for i in range(lookback_weeks, len(dates)):
            h_now = holders[i]
            h_bef = holders[i - lookback_weeks]
            if h_bef <= 0:
                continue

            flee = (h_now - h_bef) / h_bef * 100
            if flee > flee_pct_thresh:
                continue  # 散戶沒跑夠

            # 找訊號日的股價（TDCC資料對應的收盤日）
            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr):
                continue
            cp = float(parr[pi, 1])
            if cp < min_price:
                continue

            # MA20 條件
            if require_ma20:
                if np.isnan(ma20[pi]) or cp < ma20[pi]:
                    continue

            # 買入日 = TDCC公布後 delay_days 個交易日
            if pi + delay_days >= len(parr):
                continue
            buy_date = parr[pi + delay_days, 0]
            buy_price = float(parr[pi + delay_days, 1])
            if buy_price <= 0:
                continue

            sigs[buy_date].append((code, buy_price))
            sig_details.append({
                'code': code,
                'tdcc_date': dates[i],
                'buy_date': buy_date,
                'buy_price': buy_price,
                'flee_pct': flee,
                'holders_now': h_now,
                'holders_bef': h_bef,
                'price_tdcc': cp,
                'ma20': float(ma20[pi]) if not np.isnan(ma20[pi]) else None,
            })

    return sigs, sig_details


# ══════════════════════════════════════════════════════════════
# STEP 0: 邏輯確認 — 看看訊號長什麼樣
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 0: 訊號樣本確認（前20筆）")
print("=" * 90)

sigs_b, details_b = gen_b_signals()
print(f"  總訊號數: {sum(len(v) for v in sigs_b.values())}  訊號日期數: {len(sigs_b)}")
print()
print(f"  {'代碼':>6} {'TDCC日':>10} {'買入日':>10} {'買價':>7} {'散戶跑%':>8} {'持有人':>8} {'股價/MA20':>10}")
for d in sorted(details_b, key=lambda x: x['tdcc_date'])[:20]:
    ratio = d['price_tdcc'] / d['ma20'] if d['ma20'] else 0
    print(f"  {d['code']:>6} {d['tdcc_date']:>10} {d['buy_date']:>10} "
          f"{d['buy_price']:>7.1f} {d['flee_pct']:>+7.1f}% "
          f"{d['holders_now']:>8,} {ratio:>9.2f}x")


# ══════════════════════════════════════════════════════════════
# STEP 1: 前瞻偏差檢查
# TDCC 每週五公布「上週五」的資料，約有 5~7 個交易日延遲
# 我們的設定：delay_days=5（下一週買），理論上沒有前瞻
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 1: 不同買入延遲測試（確認沒有前瞻偏差）")
print("=" * 90)
print("  [說明] 若 delay=1 和 delay=5 差距不大，代表沒有偷看未來的問題")
print(f"  {'延遲天數':10s} | {'報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率':>6} | 訊號數")

for delay in [1, 3, 5, 7, 10]:
    sigs_d, _ = gen_b_signals(delay_days=delay)
    n_sigs = sum(len(v) for v in sigs_d.values())
    m = backtest(sigs_d, price_idx, all_dates)
    if m:
        print(f"  delay={delay}天{' '*5}  | {m['ret']:>+7.1f}% | {m['dd']:>7.1f}% "
              f"| {m['calmar']:>6.2f} | {m['wr']:>5.0f}% | {n_sigs}")


# ══════════════════════════════════════════════════════════════
# STEP 2: Out-of-sample 驗證
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 2: Out-of-Sample 驗證")
print("=" * 90)

sigs_b5, _ = gen_b_signals(delay_days=5)

for label, dr in [
    ("全期 2022-2025",  ('20220101', '20251231')),
    ("訓練 2022-2023",  ('20220101', '20231231')),
    ("測試 2024-2025",  ('20240101', '20251231')),
    ("測試 2024",       ('20240101', '20241231')),
    ("測試 2025",       ('20250101', '20251231')),
]:
    m = backtest(sigs_b5, price_idx, all_dates, date_range=dr)
    if m:
        print(f"  {label:20s} | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
              f"| Calmar {m['calmar']:>6.2f} | WR {m['wr']:>4.0f}% PR {m['pr']:.1f} "
              f"| n={m['n']:>3d} SL={m['n_sl']}")


# ══════════════════════════════════════════════════════════════
# STEP 3: 敏感度測試（參數稍微改動會不會崩潰）
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 3: 敏感度測試")
print("=" * 90)

print("\n  [3a] 散戶逃跑門檻（核心參數）:")
for thresh in [-2.0, -3.0, -5.0, -7.0, -10.0, -15.0]:
    sigs_t, _ = gen_b_signals(flee_pct_thresh=thresh)
    n = sum(len(v) for v in sigs_t.values())
    m = backtest(sigs_t, price_idx, all_dates)
    if m:
        print(f"  散戶跑>{abs(thresh):.0f}%  | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
              f"| Calmar {m['calmar']:>6.2f} | WR {m['wr']:>4.0f}% | n={m['n']:>3d} 訊號:{n}")

print("\n  [3b] 回望週數（幾週跌多少人）:")
for weeks in [2, 3, 4, 6, 8]:
    sigs_t, _ = gen_b_signals(lookback_weeks=weeks)
    n = sum(len(v) for v in sigs_t.values())
    m = backtest(sigs_t, price_idx, all_dates)
    if m:
        print(f"  回望{weeks}週  | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
              f"| Calmar {m['calmar']:>6.2f} | WR {m['wr']:>4.0f}% | n={m['n']:>3d} 訊號:{n}")

print("\n  [3c] 有無 MA20 條件:")
for req_ma, label in [(True, "需要站上MA20"), (False, "不需要MA20")]:
    sigs_t, _ = gen_b_signals(require_ma20=req_ma)
    m = backtest(sigs_t, price_idx, all_dates)
    if m:
        print(f"  {label:12s} | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
              f"| Calmar {m['calmar']:>6.2f} | WR {m['wr']:>4.0f}% | n={m['n']:>3d}")

print("\n  [3d] 最低股價門檻:")
for mp in [30, 50, 100, 200, 300]:
    sigs_t, _ = gen_b_signals(min_price=mp)
    m = backtest(sigs_t, price_idx, all_dates)
    if m:
        print(f"  股價>={mp:3d}  | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
              f"| Calmar {m['calmar']:>6.2f} | WR {m['wr']:>4.0f}% | n={m['n']:>3d}")


# ══════════════════════════════════════════════════════════════
# STEP 4: 實際交易明細（找出是哪幾筆撐起來的）
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 4: 全期交易明細（確認是否有少數大贏家撐起整個績效）")
print("=" * 90)

m_full = backtest(sigs_b5, price_idx, all_dates)
if m_full:
    trades = m_full['trades']
    closed = [t for t in trades if t.exit_reason != '未平倉']
    closed.sort(key=lambda x: -x.profit)

    print(f"  總交易: {len(closed)} 筆  獲利: {sum(1 for t in closed if t.profit>0)}  虧損: {sum(1 for t in closed if t.profit<=0)}")
    print(f"  最大單筆獲利: {max(t.profit for t in closed):+,.0f}  最大單筆虧損: {min(t.profit for t in closed):+,.0f}")
    print(f"  前5大獲利佔總獲利比例: "
          f"{sum(t.profit for t in closed[:5])/sum(t.profit for t in closed if t.profit>0)*100:.0f}%")

    print()
    print(f"  {'代碼':>6} {'買日':>10} {'賣日':>10} {'報酬':>7} {'損益':>10} {'天':>4} {'出場'}")
    for t in closed[:15]:
        icon = '🟢' if t.profit > 0 else '🔴'
        print(f"  {icon}{t.code:>5} {t.buy_date} {t.sell_date} "
              f"{t.return_pct:>+6.1f}% {t.profit:>+10,.0f} {t.days_held:>3}d {t.exit_reason}")

    print("  ...")
    print(f"\n  後5筆（最差）:")
    for t in closed[-5:]:
        icon = '🟢' if t.profit > 0 else '🔴'
        print(f"  {icon}{t.code:>5} {t.buy_date} {t.sell_date} "
              f"{t.return_pct:>+6.1f}% {t.profit:>+10,.0f} {t.days_held:>3}d {t.exit_reason}")

    # 按年分布
    print(f"\n  逐年績效:")
    for yr in ['2022', '2023', '2024', '2025']:
        yr_trades = [t for t in closed if t.buy_date.startswith(yr)]
        if yr_trades:
            wins = [t for t in yr_trades if t.profit > 0]
            wr = len(wins)/len(yr_trades)*100
            avg_ret = np.mean([t.return_pct for t in yr_trades])
            total_pnl = sum(t.profit for t in yr_trades)
            print(f"  {yr}: {len(yr_trades):>3d}筆 | WR {wr:>4.0f}% | 平均報酬 {avg_ret:>+5.1f}% "
                  f"| 淨損益 {total_pnl:>+10,.0f}")


# ══════════════════════════════════════════════════════════════
# STEP 5: 與原策略比較（同期）
# ══════════════════════════════════════════════════════════════
print()
print("=" * 90)
print("  STEP 5: 策略B vs 原始v6d 完整對比")
print("=" * 90)

from strategy_v6d import load_data, prepare_data, scan_signals, StrategyConfig, simulate_portfolio

holdings_v6, prices_v6 = load_data()
cfg = StrategyConfig()
h_v6, pidx_v6, sf = prepare_data(holdings_v6, prices_v6, cfg)
sigs_v6 = scan_signals(h_v6, pidx_v6, cfg, sf)
r_v6 = simulate_portfolio(sigs_v6, pidx_v6, prices_v6, cfg)

closed_v6 = [t for t in r_v6.trades if t.exit_reason != '未平倉']
wins_v6 = [t for t in closed_v6 if t.profit > 0]
losses_v6 = [t for t in closed_v6 if t.profit <= 0]
wr_v6 = len(wins_v6)/len(closed_v6)*100 if closed_v6 else 0
pr_v6 = abs(np.mean([t.return_pct for t in wins_v6])/np.mean([t.return_pct for t in losses_v6])) if losses_v6 and wins_v6 else 0

print(f"\n  {'指標':15s} | {'原始v6d':>12} | {'策略B':>12}")
print(f"  {'─'*45}")
m_b = backtest(sigs_b5, price_idx, all_dates)
rows = [
    ("總報酬", f"{r_v6.total_return_pct:>+.1f}%", f"{m_b['ret']:>+.1f}%"),
    ("最大回撤", f"{r_v6.max_drawdown_pct:>.1f}%", f"{m_b['dd']:>.1f}%"),
    ("Calmar", f"{r_v6.total_return_pct/abs(r_v6.max_drawdown_pct):.2f}", f"{m_b['calmar']:.2f}"),
    ("勝率", f"{wr_v6:.0f}%", f"{m_b['wr']:.0f}%"),
    ("盈虧比", f"{pr_v6:.1f}", f"{m_b['pr']:.1f}"),
    ("交易數", f"{len(closed_v6)}", f"{m_b['n']}"),
    ("停損數", f"{sum(1 for t in closed_v6 if t.exit_reason=='停損')}", f"{m_b['n_sl']}"),
]
for name, v, b in rows:
    better = "← B勝" if (name in ["總報酬","Calmar","勝率","盈虧比"] and float(b.replace('%','').replace('+','')) > float(v.replace('%','').replace('+',''))) or \
             (name in ["最大回撤"] and float(b.replace('%','')) > float(v.replace('%',''))) else ""
    print(f"  {name:15s} | {v:>12} | {b:>12}  {better}")
