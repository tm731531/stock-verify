"""
v7 調整測試：根據專家建議進行三項改進並驗證 Calmar 是否仍 > 3

調整一：補位引擎從「月」為單位改為「週」（讓補位有更多發揮空間）
調整二：補位引擎加入更嚴格的出逃門檻（散戶跑 >7% 才算，避免雜訊）
調整三：主引擎入場條件收緊（r400 累計漲幅 ≥ 3% 而非 2%，降低停損率）
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_main_engine, scan_backup_engine, simulate_v7,
    V7Config, print_result
)

print("載入資料...")
holdings, prices = load_data()
price_idx = build_price_index(prices)
ma_idx    = build_ma_index(price_idx, 20)


def run_v7(cfg, label, weekly_backup=False):
    """跑一次 v7 回測並印出摘要"""
    main_sigs   = scan_main_engine(holdings, price_idx, cfg)
    backup_sigs = scan_backup_engine(holdings, price_idx, cfg, ma_idx)

    if weekly_backup:
        # 以「週」為單位判斷補位是否可用
        def get_week(date_str):
            ts = pd.Timestamp(str(date_str))
            return f"{ts.year}W{ts.isocalendar()[1]:02d}"
        main_active_weeks_iso = {get_week(s.buy_date) for s in main_sigs}
        backup_filtered = [s for s in backup_sigs
                           if get_week(s.buy_date) not in main_active_weeks_iso]
    else:
        main_active_weeks = {s.buy_date[:6] for s in main_sigs}
        backup_filtered = [s for s in backup_sigs
                           if s.buy_date[:6] not in main_active_weeks]

    result = simulate_v7(main_sigs, backup_filtered, price_idx, prices, cfg)

    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    wins   = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr     = len(wins)/len(closed)*100 if closed else 0
    avg_w  = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_l  = np.mean([t.return_pct for t in losses]) if losses else 0
    pr     = abs(avg_w/avg_l) if avg_l else 0
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0
    n_sl   = sum(1 for t in closed if t.exit_reason == '停損')
    main_t = [t for t in closed if t.engine == 'main']
    back_t = [t for t in closed if t.engine == 'backup']
    n_backup_sigs = len(backup_filtered)

    print(f"\n  {'─'*85}")
    print(f"  {label}")
    print(f"  {'─'*85}")
    print(f"  報酬: {result.total_return_pct:>+7.1f}%  |  最大回撤: {result.max_drawdown_pct:>6.1f}%  |  Calmar: {calmar:>5.2f}")
    print(f"  勝率: {wr:>4.0f}%  |  盈虧比: {pr:.1f}  |  n={len(closed)}(停損{n_sl})  |  補位啟用訊號:{n_backup_sigs}")
    print(f"  主引擎: {len(main_t)} 筆  |  補位引擎: {len(back_t)} 筆")

    print(f"  逐年: ", end='')
    for yr in ['2022', '2023', '2024', '2025']:
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        yr_w = sum(1 for t in yr_t if t.profit > 0)
        yr_pnl = sum(t.profit for t in yr_t)
        print(f"{yr}:{yr_pnl:>+8,.0f}({yr_w}/{len(yr_t)}筆)  ", end='')
    print()

    return calmar, result


print()
print("="*90)
print("  v7 各版本對比（Calmar 是否仍 > 3？）")
print("="*90)

# ─── 基準：原始 v7 ─────────────────────────────────────────────────────────────
cfg_base = V7Config()
c0, r0 = run_v7(cfg_base, "基準 v7（月為單位，r400≥2%）", weekly_backup=False)

# ─── 調整一：補位改為週為單位 ─────────────────────────────────────────────────
c1, r1 = run_v7(cfg_base, "調整一：補位改為【週】為單位（主引擎空閒週才補位）", weekly_backup=True)

# ─── 調整二：補位門檻收緊（散戶跑 >7%）────────────────────────────────────────
cfg_b2 = V7Config()
cfg_b2.flee_min_pct = -7.0
c2, r2 = run_v7(cfg_b2, "調整二：補位門檻收緊（散戶跑>7%，週為單位）", weekly_backup=True)

# ─── 調整三：主引擎 r400 門檻提高（≥3%）────────────────────────────────────────
cfg_b3 = V7Config()
cfg_b3.flee_min_pct = -7.0
cfg_b3.min_r400_chg = 3.0
c3, r3 = run_v7(cfg_b3, "調整三：主引擎 r400≥3%（更嚴格，週補位，散戶>7%）", weekly_backup=True)

# ─── 調整四：主引擎 r400≥3% + 補位門檻放寬（散戶>5%）──────────────────────────
cfg_b4 = V7Config()
cfg_b4.flee_min_pct = -5.0
cfg_b4.min_r400_chg = 3.0
c4, r4 = run_v7(cfg_b4, "調整四：主引擎r400≥3% + 補位散戶>5%（週補位）", weekly_backup=True)

# ─── 調整五：主引擎 r400≥3% + 補位散戶>5% + 更緊追蹤停利 ─────────────────────
cfg_b5 = V7Config()
cfg_b5.flee_min_pct = -5.0
cfg_b5.min_r400_chg = 3.0
cfg_b5.trailing_activate_pct = 12.0
cfg_b5.trailing_stop_pct = 8.0
c5, r5 = run_v7(cfg_b5, "調整五：+收緊追蹤停利（漲12%啟動，回落8%出場）", weekly_backup=True)


# ─── 詳細印出最佳版本 ─────────────────────────────────────────────────────────
results = [
    ("基準 v7", c0, r0, cfg_base, False),
    ("調整一（週補位）", c1, r1, cfg_base, True),
    ("調整二（週補位+散戶>7%）", c2, r2, cfg_b2, True),
    ("調整三（週補位+r400≥3%+散戶>7%）", c3, r3, cfg_b3, True),
    ("調整四（週補位+r400≥3%+散戶>5%）", c4, r4, cfg_b4, True),
    ("調整五（+收緊trailing）", c5, r5, cfg_b5, True),
]
best_label, best_c, best_r, best_cfg, best_weekly = max(results, key=lambda x: x[1])

print()
print("="*90)
print(f"  最佳版本：{best_label}  (Calmar {best_c:.2f})")
print("="*90)
print_result(best_r, best_cfg, f"v7 最佳調整版 — {best_label}")

print()
print("="*90)
print("  所有版本 Calmar 對比")
print("="*90)
for label, c, _, _, _ in results:
    bar = '█' * int(c * 2) if c > 0 else ''
    flag = '✅' if c >= 3 else '⚠️'
    print(f"  {flag} {label:40s} Calmar {c:>5.2f}  {bar}")
