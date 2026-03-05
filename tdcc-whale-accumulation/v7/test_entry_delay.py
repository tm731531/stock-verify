"""
測試主引擎不同入場延遲天數的影響
delay=0：訊號日當天就買
delay=1：隔1個交易日買
delay=3：隔3個交易日買（目前設定）
delay=5：隔5個交易日買
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_backup_engine, simulate_v7,
    V7Config, Signal
)

print("載入資料...")
holdings, prices = load_data()
price_idx = build_price_index(prices)
ma_idx    = build_ma_index(price_idx, 20)


def scan_main_with_delay(holdings, price_idx, cfg, delay):
    """主引擎掃描，可調整入場延遲天數"""
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

            after = parr[parr[:, 0] > dates[i]]
            if delay == 0:
                # 訊號日當天收盤買
                if pi < len(parr) and parr[pi, 0] == dates[i]:
                    signals.append(Signal(
                        code=code, engine='main',
                        signal_date=dates[i],
                        buy_date=dates[i],
                        buy_price=price,
                        streak=streak, r400_chg=r400_chg,
                        sync=sync, holder_chg_pct=h_chg,
                    ))
            else:
                if len(after) < delay + 1: continue
                limit = price * 1.03
                window = after[delay:delay+5]
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


def run(delay):
    cfg = V7Config()
    main_sigs = scan_main_with_delay(holdings, price_idx, cfg, delay)

    backup_sigs = scan_backup_engine(holdings, price_idx, cfg, ma_idx)

    def iso_week(d):
        ts = pd.Timestamp(str(d))
        return f"{ts.year}W{ts.isocalendar()[1]:02d}"

    main_iso = {iso_week(s.buy_date) for s in main_sigs}
    backup_pre = [s for s in backup_sigs if iso_week(s.buy_date) not in main_iso]
    main_active_months = {s.buy_date[:6] for s in main_sigs}
    backup_filtered = [s for s in backup_pre if s.buy_date[:6] not in main_active_months]

    result = simulate_v7(main_sigs, backup_filtered, price_idx, prices, cfg)

    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    main_t = [t for t in closed if t.engine == 'main']
    wins   = [t for t in main_t if t.profit > 0]
    losses = [t for t in main_t if t.profit <= 0]
    wr     = len(wins)/len(main_t)*100 if main_t else 0
    avg_w  = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_l  = np.mean([t.return_pct for t in losses]) if losses else 0
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0

    # 主引擎平均買入偏離（買入價 vs 訊號日收盤）
    deviations = []
    for s in main_sigs:
        parr = price_idx.get(s.code)
        if parr is None: continue
        pi = np.searchsorted(parr[:, 0], s.signal_date)
        if pi >= len(parr) or parr[pi, 0] != s.signal_date: continue
        sig_price = float(parr[pi, 1])
        dev = (s.buy_price - sig_price) / sig_price * 100
        deviations.append(dev)
    avg_dev = np.mean(deviations) if deviations else 0

    print(f"\n  延遲 {delay} 天（訊號後第{delay}個交易日起買）")
    print(f"  ├ 總報酬: {result.total_return_pct:>+7.1f}%  最大回撤: {result.max_drawdown_pct:>6.1f}%  Calmar: {calmar:>5.2f}")
    print(f"  ├ 主引擎: {len(main_t)}筆  勝率: {wr:.0f}%  均贏: {avg_w:+.1f}%  均虧: {avg_l:+.1f}%")
    print(f"  ├ 平均買入偏離訊號日: {avg_dev:+.2f}%（正=追高，負=低接）")
    print(f"  └ 逐年: ", end='')
    for yr in ['2022','2023','2024','2025']:
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        pnl  = sum(t.profit for t in yr_t)
        print(f"{yr}:{pnl:>+8,.0f}  ", end='')
    print()
    return calmar


print()
print("=" * 80)
print("  主引擎入場延遲天數測試（補位引擎設定不變）")
print("=" * 80)

results = []
for d in [0, 1, 2, 3, 4, 5]:
    c = run(d)
    results.append((d, c))

print()
print("=" * 80)
print("  Calmar 對比")
print("=" * 80)
best = max(results, key=lambda x: x[1])
for d, c in results:
    bar  = '█' * int(c * 2)
    mark = ' ← 目前設定' if d == 3 else (' ← 最佳' if d == best[0] and d != 3 else '')
    print(f"  延遲 {d} 天  Calmar {c:>5.2f}  {bar}{mark}")
