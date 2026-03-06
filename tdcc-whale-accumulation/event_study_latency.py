#!/usr/bin/env python3
"""
潛伏期分析：ratio_400_above 顯著變化前後的股價行為 (Event Study)

分析邏輯：
1. 識別所有 ratio_400_above 顯著變化的事件（週），定義為 |change| >= 中位數的 2 倍
2. 排除：ETF (00%)、ratio_400=100、holders<=5
3. 對每個事件，收集：
   - 基準點（0%）= 事件當週 TDCC date 對應的 daily_prices 收盤價
   - "事件前 N 週" = holdings 中該股票前 N 筆 TDCC 資料對應的收盤價
   - "事件後 N 週" = daily_prices 中 事件日期 + N*7 天後最近的收盤價
4. 計算股價相對變化（基準點為 0%）
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict
import sys

# 解析命令行參數 (start_idx, end_idx)
start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end_idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
agent_name = sys.argv[3] if len(sys.argv) > 3 else "default"

# 連線設定
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="tdcc",
    user="tdcc",
    password="tdcc1234"
)

cursor = conn.cursor(cursor_factory=RealDictCursor)

# ============================================================================
# 第 1 步：取得所有 TDCC 日期和股票基本資料
# ============================================================================
print("=" * 80)
print("第 1 步：初始化數據")
print("=" * 80)

cursor.execute("""
    SELECT DISTINCT date
    FROM holdings
    ORDER BY date
""")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
print(f"✓ 取得 {len(all_dates)} 個 TDCC 日期")

date_to_idx = {d: i for i, d in enumerate(all_dates)}

# 取得所有股票清單（排除 ETF）
cursor.execute("""
    SELECT DISTINCT stock_code
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    ORDER BY stock_code
""")
all_stock_codes = [row['stock_code'] for row in cursor.fetchall()]

# 根據參數過濾股票範圍
if end_idx is None:
    end_idx = len(all_stock_codes)
stock_codes = all_stock_codes[start_idx:end_idx]
print(f"✓ 取得 {len(all_stock_codes)} 支股票，本次處理 [{start_idx}:{end_idx}] = {len(stock_codes)} 支")
print(f"  範圍：{stock_codes[0] if stock_codes else 'N/A'} ~ {stock_codes[-1] if stock_codes else 'N/A'}")

# ============================================================================
# 第 2 步：計算每支股票每週 ratio_400_above 的變化幅度
# ============================================================================
print("\n" + "=" * 80)
print("第 2 步：計算 ratio_400_above 變化幅度")
print("=" * 80)

all_changes = []  # [(stock_code, date, change, ratio_400_before, ratio_400_after, total_holders)]

for stock_code in stock_codes:
    cursor.execute("""
        SELECT date, ratio_400_above, total_holders
        FROM holdings
        WHERE stock_code = %s
        ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 2:
        continue

    for i in range(1, len(rows)):
        prev_row = rows[i-1]
        curr_row = rows[i]

        # 排除條件：ratio_400=100、total_holders<=5
        if curr_row['ratio_400_above'] == 100 or curr_row['total_holders'] is None or curr_row['total_holders'] <= 5:
            continue
        if prev_row['ratio_400_above'] is None or curr_row['ratio_400_above'] is None:
            continue

        prev_ratio = float(prev_row['ratio_400_above']) if prev_row['ratio_400_above'] is not None else None
        curr_ratio = float(curr_row['ratio_400_above']) if curr_row['ratio_400_above'] is not None else None

        if prev_ratio is None or curr_ratio is None:
            continue

        # 計算相對變化幅度
        change = (curr_ratio - prev_ratio) / (abs(prev_ratio) + 1e-6)

        all_changes.append({
            'stock_code': stock_code,
            'date': curr_row['date'],
            'date_idx': date_to_idx.get(curr_row['date']),
            'change': change,
            'ratio_before': prev_ratio,
            'ratio_after': curr_ratio,
            'total_holders': curr_row['total_holders']
        })

print(f"✓ 計算了 {len(all_changes)} 條變化記錄")

if len(all_changes) == 0:
    print("❌ 沒有有效的變化事件")
    cursor.close()
    conn.close()
    exit(1)

# ============================================================================
# 第 3 步：識別"顯著事件"（變化幅度 >= 中位數的 2 倍）
# ============================================================================
print("\n" + "=" * 80)
print("第 3 步：識別顯著事件")
print("=" * 80)

changes_abs = [abs(c['change']) for c in all_changes]
median_abs_change = np.median(changes_abs)
threshold = 2 * median_abs_change

print(f"  絕對變化幅度中位數: {median_abs_change:.4f}")
print(f"  顯著事件閾值（2倍中位數）: {threshold:.4f}")

significant_events = [
    c for c in all_changes
    if abs(c['change']) >= threshold
]

print(f"✓ 識別了 {len(significant_events)} 個顯著事件（{len(significant_events)/len(all_changes)*100:.1f}%）")

if len(significant_events) == 0:
    print("❌ 沒有顯著事件")
    cursor.close()
    conn.close()
    exit(1)

# ============================================================================
# 第 4 步：對每個顯著事件，收集前 4 週、基準點、後 4 週的股價
# ============================================================================
print("\n" + "=" * 80)
print("第 4 步：收集事件前後股價")
print("=" * 80)

event_study_results = []

for event in significant_events:
    stock_code = event['stock_code']
    event_date = event['date']
    event_idx = event['date_idx']

    if event_idx is None:
        continue

    # ─────────────────────────────────────────────────────────────────────────
    # A. 取基準點（event_date 對應的收盤價）
    # ─────────────────────────────────────────────────────────────────────────
    cursor.execute("""
        SELECT close_price FROM daily_prices
        WHERE stock_code = %s AND date = %s
    """, (stock_code, event_date))

    base_row = cursor.fetchone()
    if not base_row or base_row['close_price'] is None or base_row['close_price'] == 0:
        continue

    base_price = base_row['close_price']

    # ─────────────────────────────────────────────────────────────────────────
    # B. 取事件前 4 週的股價（holdings 中前 4 筆記錄）
    # ─────────────────────────────────────────────────────────────────────────
    before_prices = {}  # {-4, -3, -2, -1} => price

    for weeks_back in [1, 2, 3, 4]:
        prev_idx = event_idx - weeks_back
        if prev_idx >= 0:
            prev_date = all_dates[prev_idx]
            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (stock_code, prev_date))

            prev_row = cursor.fetchone()
            if prev_row and prev_row['close_price'] is not None and prev_row['close_price'] != 0:
                before_prices[f'-{weeks_back}w'] = prev_row['close_price']

    # ─────────────────────────────────────────────────────────────────────────
    # C. 取事件後 4 週的股價（daily_prices 中 event_date + N*7 天後最近的收盤價）
    # ─────────────────────────────────────────────────────────────────────────
    after_prices = {}  # {1, 2, 3, 4} => price

    for weeks_forward in [1, 2, 3, 4]:
        target_date_str = (datetime.strptime(event_date, '%Y%m%d') + timedelta(days=weeks_forward*7)).strftime('%Y%m%d')

        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date >= %s
            ORDER BY date LIMIT 1
        """, (stock_code, target_date_str))

        future_row = cursor.fetchone()
        if future_row and future_row['close_price'] is not None and future_row['close_price'] != 0:
            after_prices[f'+{weeks_forward}w'] = future_row['close_price']

    # ─────────────────────────────────────────────────────────────────────────
    # D. 計算相對變化（基準點為 0%）
    # ─────────────────────────────────────────────────────────────────────────
    result = {
        'stock_code': stock_code,
        'event_date': event_date,
        'ratio_change': event['change'],
        'ratio_before': event['ratio_before'],
        'ratio_after': event['ratio_after'],
        'total_holders': event['total_holders'],
        'base_price': base_price,
    }

    # 添加前向價格和報酬
    for label, price in after_prices.items():
        ret = (price - base_price) / base_price
        result[f'price_{label}'] = price
        result[f'return_{label}'] = ret

    # 添加後向價格和報酬（用於驗證潛伏期）
    for label, price in before_prices.items():
        ret = (price - base_price) / base_price
        result[f'price_{label}'] = price
        result[f'return_{label}'] = ret

    event_study_results.append(result)

print(f"✓ 收集了 {len(event_study_results)} 個完整事件")

# ============================================================================
# 第 5 步：分析與統計
# ============================================================================
print("\n" + "=" * 80)
print("第 5 步：潛伏期分析結果")
print("=" * 80)

df = pd.DataFrame(event_study_results)

# 按 ratio_change 符號分組
positive_events = df[df['ratio_change'] > 0]
negative_events = df[df['ratio_change'] < 0]

print(f"\n【事件分類】")
print(f"  正向事件（大戶持股增加）: {len(positive_events)} 個")
print(f"  負向事件（大戶持股減少）: {len(negative_events)} 個")

# ─────────────────────────────────────────────────────────────────────────
# 分析正向事件的前後股價表現
# ─────────────────────────────────────────────────────────────────────────
def analyze_events(df_subset, event_type):
    print(f"\n【{event_type}事件（n={len(df_subset)}）的股價路徑】")
    print("週期".ljust(10) + "平均報酬".ljust(15) + "中位報酬".ljust(15) + "勝率".ljust(10) + "樣本數")
    print("-" * 60)

    # 按時間窗口分析
    time_windows = ['-4w', '-3w', '-2w', '-1w', '+0w', '+1w', '+2w', '+3w', '+4w']

    for window in time_windows:
        col = f'return_{window}'
        if col not in df_subset.columns:
            continue

        valid = df_subset[col].dropna()
        if len(valid) == 0:
            continue

        mean_ret = valid.mean()
        median_ret = valid.median()
        win_rate = (valid > 0).sum() / len(valid)

        window_label = window.replace('+0w', 'BASE')
        print(f"{window_label:10s} {mean_ret*100:7.2f}%{' '*7} {median_ret*100:7.2f}%{' '*7} {win_rate*100:5.1f}%{' '*4} {len(valid):4d}")

analyze_events(positive_events, "正向")
analyze_events(negative_events, "負向")

# ============================================================================
# 第 6 步：輸出結果表
# ============================================================================
print("\n" + "=" * 80)
print("第 6 步：完整結果表")
print("=" * 80)

# 準備輸出表格
output_columns = [
    'stock_id', 'event_date', 'ratio_before', 'ratio_after', 'ratio_change',
    'holders', 'base_price',
    'return_-4w', 'return_-3w', 'return_-2w', 'return_-1w',
    'return_+1w', 'return_+2w', 'return_+3w', 'return_+4w'
]

output_columns = [col for col in output_columns if col in df.columns]
output_df = df[output_columns].copy()

# 按 ratio_change 排序（正向優先）
output_df = output_df.sort_values('ratio_change', ascending=False)

print("\n前 20 個事件（按 ratio_change 排序）：")
print(output_df.head(20).to_string())

# 保存完整結果
output_file = f'/home/tom/stock-verify/tdcc-whale-accumulation/event_study_latency_{agent_name}_{start_idx}_{end_idx}.csv'
output_df.to_csv(
    output_file,
    index=False
)
print(f"\n✓ 完整結果已保存到 {output_file}")

# ============================================================================
# 第 7 步：統計摘要
# ============================================================================
print("\n" + "=" * 80)
print("第 7 步：統計摘要")
print("=" * 80)

summary_data = {
    '指標': [],
    '正向事件': [],
    '負向事件': []
}

metrics = [
    ('1週後平均報酬', 'return_+1w'),
    ('2週後平均報酬', 'return_+2w'),
    ('4週後平均報酬', 'return_+4w'),
    ('1週後勝率', 'return_+1w'),
    ('2週後勝率', 'return_+2w'),
    ('4週後勝率', 'return_+4w'),
]

for label, col in metrics:
    summary_data['指標'].append(label)

    # 正向事件
    if col in positive_events.columns:
        valid = positive_events[col].dropna()
        if '勝率' in label:
            value = f"{(valid > 0).sum() / len(valid) * 100:.1f}%"
        else:
            value = f"{valid.mean() * 100:.2f}%"
    else:
        value = "N/A"
    summary_data['正向事件'].append(value)

    # 負向事件
    if col in negative_events.columns:
        valid = negative_events[col].dropna()
        if '勝率' in label:
            value = f"{(valid > 0).sum() / len(valid) * 100:.1f}%"
        else:
            value = f"{valid.mean() * 100:.2f}%"
    else:
        value = "N/A"
    summary_data['負向事件'].append(value)

summary_df = pd.DataFrame(summary_data)
print("\n" + summary_df.to_string(index=False))

cursor.close()
conn.close()

print("\n" + "=" * 80)
print("✓ 潛伏期分析完成")
print("=" * 80)
