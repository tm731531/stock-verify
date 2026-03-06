#!/usr/bin/env python3
"""
生成版本對比圖表
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

# 設定中文字體
mpl.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
mpl.rcParams['axes.unicode_minus'] = False

# 數據
versions = [4, 6, 7, 8, 13]
annualized = [48.5, 52.9, 60.5, 57.5, 55.8]
total_trades = [230, 201, 186, 179, 148]
win_rate = [45.7, 43.3, 45.2, 43.0, 39.2]
avg_return = [4.14, 5.17, 6.39, 6.32, 7.42]
hold_period_return = [12.52, 17.85, 22.04, 23.67, 41.47]
trailing_stop_count = [8, 15, 20, 22, 32]

# 創建圖表
fig = plt.figure(figsize=(16, 12))

# 1. 年化報酬率
ax1 = plt.subplot(3, 3, 1)
bars1 = ax1.bar(versions, annualized, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax1.axhline(y=50, color='r', linestyle='--', alpha=0.3, label='50% 基準')
ax1.set_ylabel('年化報酬%', fontsize=11, fontweight='bold')
ax1.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax1.set_title('年化報酬率對比', fontsize=12, fontweight='bold')
ax1.grid(axis='y', alpha=0.3)
for i, (v, bar) in enumerate(zip(annualized, bars1)):
    ax1.text(v+0.5, v+1, f'{v:.1f}%', ha='left', fontsize=9, fontweight='bold')

# 2. 交易數量
ax2 = plt.subplot(3, 3, 2)
bars2 = ax2.bar(versions, total_trades, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax2.set_ylabel('交易數', fontsize=11, fontweight='bold')
ax2.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax2.set_title('總交易數對比', fontsize=12, fontweight='bold')
ax2.grid(axis='y', alpha=0.3)
for v, bar in zip(total_trades, bars2):
    ax2.text(v+2, v, f'{int(v)}', ha='left', fontsize=9, fontweight='bold')

# 3. 勝率
ax3 = plt.subplot(3, 3, 3)
bars3 = ax3.bar(versions, win_rate, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax3.axhline(y=50, color='r', linestyle='--', alpha=0.3, label='50% 基準')
ax3.set_ylabel('勝率%', fontsize=11, fontweight='bold')
ax3.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax3.set_title('勝率對比', fontsize=12, fontweight='bold')
ax3.set_ylim([30, 50])
ax3.grid(axis='y', alpha=0.3)
for v, bar in zip(win_rate, bars3):
    ax3.text(v+0.3, v, f'{v:.1f}%', ha='left', fontsize=9, fontweight='bold')

# 4. 平均報酬
ax4 = plt.subplot(3, 3, 4)
bars4 = ax4.bar(versions, avg_return, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax4.set_ylabel('平均報酬%', fontsize=11, fontweight='bold')
ax4.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax4.set_title('每筆平均報酬對比', fontsize=12, fontweight='bold')
ax4.grid(axis='y', alpha=0.3)
for v, bar in zip(avg_return, bars4):
    ax4.text(v+0.1, v, f'{v:.2f}%', ha='left', fontsize=9, fontweight='bold')

# 5. 期滿出場回報
ax5 = plt.subplot(3, 3, 5)
bars5 = ax5.bar(versions, hold_period_return, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax5.set_ylabel('期滿出場平均報酬%', fontsize=11, fontweight='bold')
ax5.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax5.set_title('期滿出場回報對比', fontsize=12, fontweight='bold')
ax5.grid(axis='y', alpha=0.3)
for v, bar in zip(hold_period_return, bars5):
    ax5.text(v+0.5, v, f'{v:.2f}%', ha='left', fontsize=9, fontweight='bold')

# 6. 追蹤止盈交易數
ax6 = plt.subplot(3, 3, 6)
bars6 = ax6.bar(versions, trailing_stop_count, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax6.set_ylabel('追蹤止盈交易數', fontsize=11, fontweight='bold')
ax6.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax6.set_title('追蹤止盈交易對比', fontsize=12, fontweight='bold')
ax6.grid(axis='y', alpha=0.3)
for v, bar in zip(trailing_stop_count, bars6):
    ax6.text(v+0.5, v, f'{int(v)}', ha='left', fontsize=9, fontweight='bold')

# 7. 年化 vs 交易數 散點圖
ax7 = plt.subplot(3, 3, 7)
scatter = ax7.scatter(total_trades, annualized, s=[500]*len(versions),
                     c=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.6)
for i, v in enumerate(versions):
    ax7.annotate(f'{v}週', (total_trades[i], annualized[i]),
                xytext=(5, 5), textcoords='offset points', fontsize=9, fontweight='bold')
ax7.set_xlabel('交易數', fontsize=11, fontweight='bold')
ax7.set_ylabel('年化報酬%', fontsize=11, fontweight='bold')
ax7.set_title('年化 vs 交易數（效率邊界）', fontsize=12, fontweight='bold')
ax7.grid(alpha=0.3)

# 8. 每筆平均利潤
ax8 = plt.subplot(3, 3, 8)
avg_pnl = [t_pnl / t_count for t_pnl, t_count in
           zip([158.46*5000/100, 173.04*5000/100, 197.95*5000/100, 188.07*5000/100, 182.53*5000/100],
               total_trades)]
bars8 = ax8.bar(versions, avg_pnl, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax8.set_ylabel('每筆平均 PnL（元）', fontsize=11, fontweight='bold')
ax8.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax8.set_title('每筆平均利潤對比', fontsize=12, fontweight='bold')
ax8.grid(axis='y', alpha=0.3)
for v, bar in zip(avg_pnl, bars8):
    ax8.text(v+50, v, f'{int(v)}', ha='left', fontsize=9, fontweight='bold')

# 9. 綜合評分
ax9 = plt.subplot(3, 3, 9)
# 綜合評分：年化40%、交易數20%、勝率20%、穩定性20%
scores = []
for i in range(len(versions)):
    year_score = annualized[i] / max(annualized) * 40
    trade_score = total_trades[i] / max(total_trades) * 20
    win_score = win_rate[i] / max(win_rate) * 20
    # 穩定性（中位數不好的版本扣分）
    stability = [15, 10, 12, 5, 0]  # 4,6,7,8,13周的穩定性評分
    total_score = year_score + trade_score + win_score + stability[i]
    scores.append(total_score)

bars9 = ax9.bar(versions, scores, color=['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6'], alpha=0.7)
ax9.set_ylabel('綜合評分', fontsize=11, fontweight='bold')
ax9.set_xlabel('持倉週數', fontsize=11, fontweight='bold')
ax9.set_title('綜合評分（年40% + 交易20% + 勝率20% + 穩定20%）', fontsize=12, fontweight='bold')
ax9.set_ylim([0, 100])
ax9.grid(axis='y', alpha=0.3)
for v, bar in zip(scores, bars9):
    ax9.text(v+1, v, f'{v:.1f}', ha='left', fontsize=9, fontweight='bold')

plt.tight_layout()
plt.savefig('/home/tom/stock-verify/tdcc-whale-accumulation/version_comparison_charts.png', dpi=150, bbox_inches='tight')
print("✓ 圖表已保存：version_comparison_charts.png")

# 生成詳細數據表
df_comparison = pd.DataFrame({
    '週數': versions,
    '年化%': annualized,
    '交易數': total_trades,
    '勝率%': win_rate,
    '平均回報%': avg_return,
    '期滿回報%': hold_period_return,
    '追蹤止盈數': trailing_stop_count,
    '綜合評分': scores,
})

print("\n" + "="*80)
print("版本對比數據表")
print("="*80)
print(df_comparison.to_string(index=False))
print()

# 保存為 CSV
df_comparison.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/version_comparison_summary.csv', index=False)
print("✓ 對比表已保存：version_comparison_summary.csv")
