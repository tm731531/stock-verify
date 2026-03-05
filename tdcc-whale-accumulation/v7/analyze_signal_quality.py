"""分析主引擎訊號品質：短期大量 vs 長期慢慢買"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from strategy_v7 import (
    load_data, build_price_index, build_ma_index,
    scan_main_engine, scan_backup_engine, simulate_v7, V7Config
)

holdings, prices = load_data()
price_idx = build_price_index(prices)
cfg = V7Config()

main_sigs = scan_main_engine(holdings, price_idx, cfg)
backup_sigs = scan_backup_engine(holdings, price_idx, cfg, build_ma_index(price_idx, 20))

def iso_week(d):
    ts = pd.Timestamp(str(d))
    return f'{ts.year}W{ts.isocalendar()[1]:02d}'

main_iso = {iso_week(s.buy_date) for s in main_sigs}
backup_active = [s for s in backup_sigs if iso_week(s.buy_date) not in main_iso]
result = simulate_v7(main_sigs, backup_active, price_idx, prices, cfg)

closed = [t for t in result.trades if t.exit_reason != '未平倉' and t.engine == 'main']
sig_map = {(s.code, s.buy_date): s for s in main_sigs}

print(f"{'':2}{'代碼':>6} {'連升':>4} {'r400↑':>7} {'週速率':>7} {'報酬':>7}  出場")
print('-' * 60)

rows = []
for t in sorted(closed, key=lambda x: x.return_pct, reverse=True):
    sig = sig_map.get((t.code, t.buy_date))
    if not sig: continue
    weekly_rate = sig.r400_chg / sig.streak
    win = t.profit > 0
    marker = '🟢' if win else '🔴'
    print(f"{marker}{t.code:>5} {sig.streak:>4}週 {sig.r400_chg:>+6.1f}% {weekly_rate:>+6.2f}%/週 {t.return_pct:>+6.1f}%  {t.exit_reason}")
    rows.append({'win': win, 'streak': sig.streak, 'r400_chg': sig.r400_chg,
                 'weekly_rate': weekly_rate, 'return_pct': t.return_pct})

df = pd.DataFrame(rows)
win = df[df.win]
lose = df[~df.win]

print()
print('='*60)
print(f'              獲利 {len(win)}筆          虧損 {len(lose)}筆')
print(f'  連升週數:   {win.streak.mean():.1f} 週           {lose.streak.mean():.1f} 週')
print(f'  r400 累計:  {win.r400_chg.mean():+.1f}%           {lose.r400_chg.mean():+.1f}%')
print(f'  每週速率:   {win.weekly_rate.mean():+.2f}%/週       {lose.weekly_rate.mean():+.2f}%/週')
print(f'  平均報酬:   {win.return_pct.mean():+.1f}%           {lose.return_pct.mean():+.1f}%')
print()

# 按週速率分組看勝率
df['speed_group'] = pd.cut(df.weekly_rate, bins=[0, 1, 2, 3, 99],
                            labels=['<1%/週', '1-2%/週', '2-3%/週', '>3%/週'])
grp = df.groupby('speed_group', observed=True).agg(
    筆數=('win', 'count'),
    勝率=('win', lambda x: f"{x.mean()*100:.0f}%"),
    均報酬=('return_pct', lambda x: f"{x.mean():+.1f}%"),
).reset_index()
print('按每週速率分組:')
print(grp.to_string(index=False))

print()
df['streak_group'] = pd.cut(df.streak, bins=[0, 3, 5, 7, 99],
                             labels=['3週', '4-5週', '6-7週', '8週+'])
grp2 = df.groupby('streak_group', observed=True).agg(
    筆數=('win', 'count'),
    勝率=('win', lambda x: f"{x.mean()*100:.0f}%"),
    均報酬=('return_pct', lambda x: f"{x.mean():+.1f}%"),
).reset_index()
print('按連升週數分組:')
print(grp2.to_string(index=False))
