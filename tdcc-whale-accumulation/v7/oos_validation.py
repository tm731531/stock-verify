"""
Out-of-sample 驗證
訓練期: 2022-2023 (找最佳參數)
測試期: 2024-2025 (未見資料驗證)
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v6d import load_data, prepare_data, scan_signals, StrategyConfig
from analysis_deep import simulate

TRAIN = ('20220101', '20231231')
TEST  = ('20240101', '20251231')
FULL  = ('20220101', '20251231')


def run(signals, price_idx, prices, cfg, params, period):
    ma_p, sl, ta, ts, mh, min_r4 = params
    r, c = simulate(signals, price_idx, prices, cfg,
                    ma_period=ma_p, stop_loss=sl,
                    trail_activate=ta, trail_stop=ts,
                    max_hold=mh, min_r400=min_r4,
                    date_range=period)
    if r is None:
        return None
    closed = [t for t in r.trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    avg_win = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.return_pct for t in losses]) if losses else 0
    pr = abs(avg_win/avg_loss) if avg_loss else 0
    n_sl = sum(1 for t in closed if t.exit_reason == '停損')
    return dict(ret=r.total_return_pct, dd=r.max_drawdown_pct,
                calmar=c, wr=wr, pr=pr, n=len(closed), n_sl=n_sl)


print("載入資料...")
holdings, prices = load_data()
cfg = StrategyConfig()
holdings, price_idx, special_flag = prepare_data(holdings, prices, cfg)
signals = scan_signals(holdings, price_idx, cfg, special_flag)
print(f"總訊號: {len(signals)}")
print(f"  訓練期訊號: {sum(1 for s in signals if TRAIN[0]<=s.buy_date<=TRAIN[1])}")
print(f"  測試期訊號: {sum(1 for s in signals if TEST[0]<=s.buy_date<=TEST[1])}")

# ══════════════════════════════════════════════════════════════
# STEP 1: 在訓練期（2022-2023）掃描所有參數組合
# ══════════════════════════════════════════════════════════════
print("\n訓練期暴力搜尋 (2022-2023)...")
train_results = []

for ma_p in [None, 20, 30]:
    for sl in [-5.0, -6.0, -7.0]:
        for ta in [10.0, 12.0, 15.0]:
            for ts in [7.0, 8.0, 10.0]:
                for mh in [45, 60, 90]:
                    for min_r4 in [None, 3.0]:
                        if ta <= ts:
                            continue
                        params = (ma_p, sl, ta, ts, mh, min_r4)
                        m = run(signals, price_idx, prices, cfg, params, TRAIN)
                        if m and m['n'] >= 5:  # 訓練期至少5筆
                            train_results.append((params, m))

train_results.sort(key=lambda x: -x[1]['calmar'])
print(f"有效組合數: {len(train_results)}")

print()
print("=" * 110)
print("  STEP 1: 訓練期 Top 15（2022-2023）")
print("=" * 110)
print(f"  {'組合':45s} | {'IS 報酬':>8} | {'IS 回撤':>8} | {'IS Calmar':>9} | {'IS 勝率':>7} | n")
for params, m in train_results[:15]:
    ma_p, sl, ta, ts, mh, min_r4 = params
    label = f"MA{ma_p or'無'} SL{sl}% T{ta}%@{ts}% {mh}d {'r4>3' if min_r4 else ''}"
    print(f"  {label:45s} | {m['ret']:>+7.1f}% | {m['dd']:>7.1f}% | {m['calmar']:>9.2f} | {m['wr']:>6.0f}% | {m['n']}")

# ══════════════════════════════════════════════════════════════
# STEP 2: 對 Top 15 做 out-of-sample 測試（2024-2025）
# ══════════════════════════════════════════════════════════════
print()
print("=" * 120)
print("  STEP 2: Out-of-Sample 驗證（2024-2025）— 訓練期 Top 15")
print("=" * 120)
print(f"  {'組合':45s} | {'IS報酬':>8} | {'IS C':>6} | {'OOS報酬':>8} | {'OOS回撤':>8} | {'OOS C':>6} | {'OOS勝率':>7} | n_OOS | 衰減?")

decay_flag = []
for params, is_m in train_results[:15]:
    ma_p, sl, ta, ts, mh, min_r4 = params
    oos_m = run(signals, price_idx, prices, cfg, params, TEST)
    label = f"MA{ma_p or'無'} SL{sl}% T{ta}%@{ts}% {mh}d {'r4>3' if min_r4 else ''}"

    if oos_m:
        decay = oos_m['calmar'] < is_m['calmar'] * 0.5
        flag = "⚠️ 嚴重衰減" if decay else ("📉 輕微衰減" if oos_m['calmar'] < is_m['calmar'] else "✅ 穩定")
        print(f"  {label:45s} | {is_m['ret']:>+7.1f}% | {is_m['calmar']:>5.2f} "
              f"| {oos_m['ret']:>+7.1f}% | {oos_m['dd']:>7.1f}% | {oos_m['calmar']:>5.2f} "
              f"| {oos_m['wr']:>6.0f}% | {oos_m['n']:>5d} | {flag}")
        decay_flag.append((params, is_m, oos_m, decay))
    else:
        print(f"  {label:45s} | {is_m['ret']:>+7.1f}% | {is_m['calmar']:>5.2f} | 無OOS資料")

# ══════════════════════════════════════════════════════════════
# STEP 3: 基準對比
# ══════════════════════════════════════════════════════════════
print()
print("=" * 120)
print("  STEP 3: 基準策略（原始 v6d，無任何改動）")
print("=" * 120)
base_params = (None, -7.0, 15.0, 10.0, 90, None)
base_full = run(signals, price_idx, prices, cfg, base_params, FULL)
base_is   = run(signals, price_idx, prices, cfg, base_params, TRAIN)
base_oos  = run(signals, price_idx, prices, cfg, base_params, TEST)
print(f"  全期(2022-25): 報酬 {base_full['ret']:+.1f}%  DD {base_full['dd']:.1f}%  Calmar {base_full['calmar']:.2f}  WR {base_full['wr']:.0f}%  n={base_full['n']}")
print(f"  訓練(2022-23): 報酬 {base_is['ret']:+.1f}%  DD {base_is['dd']:.1f}%  Calmar {base_is['calmar']:.2f}  WR {base_is['wr']:.0f}%  n={base_is['n']}")
print(f"  測試(2024-25): 報酬 {base_oos['ret']:+.1f}%  DD {base_oos['dd']:.1f}%  Calmar {base_oos['calmar']:.2f}  WR {base_oos['wr']:.0f}%  n={base_oos['n']}")

# ══════════════════════════════════════════════════════════════
# STEP 4: 找 IS+OOS 雙穩健的方案
# ══════════════════════════════════════════════════════════════
print()
print("=" * 120)
print("  STEP 4: 雙穩健候選（IS Calmar > 1.5 且 OOS Calmar > 1.5）")
print("=" * 120)
print(f"  {'組合':45s} | {'IS Calmar':>9} | {'OOS Calmar':>10} | {'全期Calmar':>10} | {'OOS/IS':>7} | {'OOS報酬':>8} | n_OOS")

robust = []
for params, is_m, oos_m, decay in decay_flag:
    if is_m['calmar'] > 1.5 and oos_m['calmar'] > 1.5 and oos_m['n'] >= 5:
        full_m = run(signals, price_idx, prices, cfg, params, FULL)
        ratio = oos_m['calmar'] / is_m['calmar']
        robust.append((params, is_m, oos_m, full_m, ratio))

robust.sort(key=lambda x: -(x[2]['calmar']))  # 按OOS Calmar排序

for params, is_m, oos_m, full_m, ratio in robust:
    ma_p, sl, ta, ts, mh, min_r4 = params
    label = f"MA{ma_p or'無'} SL{sl}% T{ta}%@{ts}% {mh}d {'r4>3' if min_r4 else ''}"
    icon = "🏆" if oos_m['calmar'] >= 3 else ("⭐" if oos_m['calmar'] >= 2 else "")
    print(f"{icon} {label:45s} | {is_m['calmar']:>9.2f} | {oos_m['calmar']:>10.2f} "
          f"| {full_m['calmar'] if full_m else 0:>10.2f} | {ratio:>6.1f}x "
          f"| {oos_m['ret']:>+7.1f}% | {oos_m['n']}")

if not robust:
    print("  沒有找到雙穩健方案。放寬條件 (IS>1.0, OOS>1.0):")
    for params, is_m, oos_m, decay in decay_flag:
        if is_m['calmar'] > 1.0 and oos_m['calmar'] > 1.0 and oos_m['n'] >= 5:
            full_m = run(signals, price_idx, prices, cfg, params, FULL)
            ratio = oos_m['calmar'] / is_m['calmar']
            ma_p, sl, ta, ts, mh, min_r4 = params
            label = f"MA{ma_p or'無'} SL{sl}% T{ta}%@{ts}% {mh}d {'r4>3' if min_r4 else ''}"
            print(f"  {label:45s} | IS {is_m['calmar']:.2f} | OOS {oos_m['calmar']:.2f} | ratio {ratio:.1f}x")

# ══════════════════════════════════════════════════════════════
# STEP 5: 推薦方案完整報告
# ══════════════════════════════════════════════════════════════
print()
print("=" * 120)
print("  STEP 5: 推薦方案 vs 基準 完整對比")
print("=" * 120)

# 取OOS Calmar最高且IS>1.5的方案
best = robust[0] if robust else None
if best:
    bparams, bis, boos, bfull, bratio = best
    ma_p, sl, ta, ts, mh, min_r4 = bparams

    print(f"\n  推薦方案: MA{ma_p or'無'} | SL {sl}% | Trail activate {ta}% | Trail stop {ts}% | 持有 {mh}天 {'| r400>3%' if min_r4 else ''}")
    print()
    print(f"  {'指標':15s} | {'基準_訓練':>10} | {'基準_測試':>10} | {'推薦_訓練':>10} | {'推薦_測試':>10} | {'推薦_全期':>10}")
    print(f"  {'─'*70}")

    rows = [
        ("總報酬", f"{base_is['ret']:+.1f}%", f"{base_oos['ret']:+.1f}%",
         f"{bis['ret']:+.1f}%", f"{boos['ret']:+.1f}%", f"{bfull['ret']:+.1f}%" if bfull else "-"),
        ("最大回撤", f"{base_is['dd']:.1f}%", f"{base_oos['dd']:.1f}%",
         f"{bis['dd']:.1f}%", f"{boos['dd']:.1f}%", f"{bfull['dd']:.1f}%" if bfull else "-"),
        ("Calmar", f"{base_is['calmar']:.2f}", f"{base_oos['calmar']:.2f}",
         f"{bis['calmar']:.2f}", f"{boos['calmar']:.2f}", f"{bfull['calmar']:.2f}" if bfull else "-"),
        ("勝率", f"{base_is['wr']:.0f}%", f"{base_oos['wr']:.0f}%",
         f"{bis['wr']:.0f}%", f"{boos['wr']:.0f}%", "-"),
        ("交易數", f"{base_is['n']}", f"{base_oos['n']}",
         f"{bis['n']}", f"{boos['n']}", f"{bfull['n']}" if bfull else "-"),
        ("停損數", f"{base_is['n_sl']}", f"{base_oos['n_sl']}",
         f"{bis['n_sl']}", f"{boos['n_sl']}", "-"),
    ]
    for name, bi, bo, ri, ro, rf in rows:
        print(f"  {name:15s} | {bi:>10} | {bo:>10} | {ri:>10} | {ro:>10} | {rf:>10}")

    print()
    print(f"  OOS/IS Calmar 比值: {bratio:.2f}x  {'✅ 穩健' if bratio >= 0.7 else '⚠️ 衰減'}")

print()
print("分析完成")
