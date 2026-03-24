#!/usr/bin/env python3
"""
分析 ratio_400_above 單週變化幅度 vs 後續 1/2/4/8/13 週報酬分布
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

# 1. 取得所有 TDCC 日期（假設按時序排列）
cursor.execute("""
    SELECT DISTINCT date
    FROM holdings
    ORDER BY date
""")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
print(f"✓ 取得 {len(all_dates)} 個 TDCC 日期")

# 2. 建立日期 -> 索引的映射，方便計算 N 週後
date_to_idx = {d: i for i, d in enumerate(all_dates)}

# 3. 計算每支股票每週的 ratio_400_above 變化幅度
print("\n計算 ratio_400_above 變化幅度...")

# 先取得所有股票代號，排除 ETF 和極端情況
cursor.execute("""
    SELECT DISTINCT stock_code
    FROM holdings
    WHERE stock_code NOT LIKE '00%%'  -- 排除 ETF
      AND ratio_400_above < 100        -- 排除公開收購
    ORDER BY stock_code
""")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

# 根據參數過濾股票範圍
if end_idx is None:
    end_idx = len(all_stocks)
stocks_to_process = all_stocks[start_idx:end_idx]
print(f"✓ 取得 {len(all_stocks)} 支股票，本次處理 [{start_idx}:{end_idx}] = {len(stocks_to_process)} 支")
print(f"  範圍：{stocks_to_process[0] if stocks_to_process else 'N/A'} ~ {stocks_to_process[-1] if stocks_to_process else 'N/A'}")

stock_changes = defaultdict(list)  # stock_code -> [(date, change)]

for stock_code in stocks_to_process:
    cursor.execute("""
        SELECT date, ratio_400_above, total_holders
        FROM holdings
        WHERE stock_code = %s
        ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if not rows:
        continue

    # 過濾條件：排除 total_holders <= 5
    rows = [r for r in rows if r['total_holders'] is None or r['total_holders'] > 5]

    for i in range(1, len(rows)):
        prev_ratio = float(rows[i-1]['ratio_400_above']) if rows[i-1]['ratio_400_above'] is not None else None
        curr_ratio = float(rows[i]['ratio_400_above']) if rows[i]['ratio_400_above'] is not None else None

        if prev_ratio is None or curr_ratio is None:
            continue

        change = (curr_ratio - prev_ratio) / (prev_ratio + 1e-6)  # 避免除以零
        stock_changes[stock_code].append({
            'date': rows[i]['date'],
            'prev_ratio': prev_ratio,
            'curr_ratio': curr_ratio,
            'change': change
        })

print(f"✓ 計算了 {sum(len(v) for v in stock_changes.values())} 條變化記錄")

# 4. 對每個變化事件，查詢後續 1/2/4/8/13 週的收盤價
print("\n計算前向報酬...")

forward_windows = [1, 2, 4, 8, 13]  # 週數
results = []

for stock_code, changes in stock_changes.items():
    for event in changes:
        event_date = event['date']
        event_idx = date_to_idx.get(event_date)

        if event_idx is None:
            continue

        # 取事件日期的收盤價
        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (stock_code, event_date))

        base_row = cursor.fetchone()
        if not base_row or base_row['close_price'] is None:
            continue

        base_price = float(base_row['close_price'])
        if base_price == 0:
            continue

        # 對每個前向週數計算報酬
        returns = {}
        for weeks in forward_windows:
            target_date_str = (datetime.strptime(event_date, '%Y%m%d') + timedelta(days=weeks*7)).strftime('%Y%m%d')

            # 在 daily_prices 中找該股票 >= target_date 最接近的收盤價
            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date >= %s
                ORDER BY date LIMIT 1
            """, (stock_code, target_date_str))

            future_row = cursor.fetchone()
            if future_row and future_row['close_price'] is not None:
                future_price = float(future_row['close_price'])
                ret = (future_price - base_price) / base_price
                returns[f'return_{weeks}w'] = ret
            else:
                returns[f'return_{weeks}w'] = None

        # 只有當有至少一個前向報酬時才記錄
        if any(v is not None for v in returns.values()):
            result_row = {
                'stock_code': stock_code,
                'date': event_date,
                'ratio_400_change': event['change'],
                **returns
            }
            results.append(result_row)

print(f"✓ 收集了 {len(results)} 個完整事件")

# 5. 轉換為 DataFrame 進行分析
df = pd.DataFrame(results)

# 6. 分析：按 ratio_400_change 分位數分組
print("\n" + "="*80)
print("分析 ratio_400_above 變化幅度 vs 後續報酬分布")
print("="*80)

# 將變化幅度分為 5 個分位數
df['change_quintile'] = pd.qcut(df['ratio_400_change'], q=5, labels=['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)'], duplicates='drop')

summary_stats = []

for window in forward_windows:
    col = f'return_{window}w'

    # 去除 NaN
    valid_data = df[[col, 'change_quintile']].dropna()

    if len(valid_data) == 0:
        continue

    print(f"\n【{window} 週後報酬】")
    print(f"樣本數: {len(valid_data)}")

    for quintile in ['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)']:
        subset = valid_data[valid_data['change_quintile'] == quintile][col]

        if len(subset) == 0:
            continue

        mean_ret = subset.mean()
        median_ret = subset.median()
        std_ret = subset.std()
        win_rate = (subset > 0).sum() / len(subset)

        summary_stats.append({
            'window': f'{window}w',
            'quintile': quintile,
            'count': len(subset),
            'mean_return': mean_ret,
            'median_return': median_ret,
            'std_dev': std_ret,
            'win_rate': win_rate
        })

        print(f"  {quintile:10s}: 樣本={len(subset):4d} | "
              f"均值={mean_ret*100:7.2f}% | 中位={median_ret*100:7.2f}% | "
              f"勝率={win_rate*100:5.1f}%")

# 7. 輸出詳細表格
summary_df = pd.DataFrame(summary_stats)

print("\n" + "="*80)
print("完整結果表格 (CSV 格式)")
print("="*80)
print(summary_df.to_csv(index=False))

# 8. 相關性分析（跳過 - scipy 不可用）
# print("\n" + "="*80)
# print("相關性分析（Spearman 相關係數）")
# print("="*80)
#
# from scipy.stats import spearmanr
#
# for window in forward_windows:
#     col = f'return_{window}w'
#     valid_data = df[[col, 'ratio_400_change']].dropna()
#
#     if len(valid_data) > 2:
#         corr, pval = spearmanr(valid_data['ratio_400_change'], valid_data[col])
#         print(f"{window}週: 相關係數={corr:7.4f}, p-value={pval:.4e}")

cursor.close()
conn.close()

print("\n✓ 分析完成")

# 保存詳細結果
output_file = f'/home/tom/stock-verify/tdcc-whale-accumulation/ratio_400_analysis_{agent_name}_{start_idx}_{end_idx}.csv'
summary_df.to_csv(output_file, index=False)
print(f"✓ 結果已保存到 {output_file}")
