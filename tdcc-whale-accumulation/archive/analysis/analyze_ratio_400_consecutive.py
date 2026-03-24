#!/usr/bin/env python3
"""
Analyze ratio_400_above consecutive weeks vs forward returns.

For each stock, identify consecutive weeks where ratio_400_above > 0 (and != 100),
then calculate the forward return N weeks later.
"""

import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict
import sys

# 解析命令行參數 (start_idx, end_idx)
start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end_idx = int(sys.argv[2]) if len(sys.argv) > 2 else None
agent_name = sys.argv[3] if len(sys.argv) > 3 else "default"

# PostgreSQL connection
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="tdcc",
    user="tdcc",
    password="tdcc1234"
)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Step 1: Get all holdings with exclusion criteria
cur.execute("""
    SELECT
        stock_code,
        date,
        ratio_400_above,
        total_holders
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    AND ratio_400_above < 100
    AND total_holders > 5
    AND ratio_400_above > 0
    ORDER BY stock_code, date
""")

holdings_data = cur.fetchall()
print(f"Loaded {len(holdings_data)} holdings records")

# Step 2: Build consecutive weeks mapping
consecutive_weeks_map = defaultdict(list)  # (stock_code, start_date) -> count

for record in holdings_data:
    stock_code = record['stock_code']
    date_str = record['date']

    # Convert YYYYMMDD to date object
    date_obj = datetime.strptime(date_str, '%Y%m%d').date()

    consecutive_weeks_map[(stock_code, date_str)].append(date_obj)

# Step 3: Identify consecutive week sequences
consecutive_sequences = []  # List of (stock_code, start_date, consecutive_weeks_count)

cur.execute("""
    SELECT DISTINCT stock_code, date
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    AND ratio_400_above < 100
    AND total_holders > 5
    AND ratio_400_above > 0
    ORDER BY stock_code, date
""")

all_dates = cur.fetchall()

# Group by stock
stock_data = defaultdict(list)
for row in all_dates:
    stock_data[row['stock_code']].append(row['date'])

# 根據參數過濾股票範圍
all_stocks_sorted = sorted(stock_data.keys())
if end_idx is None:
    end_idx = len(all_stocks_sorted)
stocks_to_process = all_stocks_sorted[start_idx:end_idx]
print(f"✓ 取得 {len(all_stocks_sorted)} 支股票，本次處理 [{start_idx}:{end_idx}] = {len(stocks_to_process)} 支")
print(f"  範圍：{stocks_to_process[0] if stocks_to_process else 'N/A'} ~ {stocks_to_process[-1] if stocks_to_process else 'N/A'}")

# For each stock, identify consecutive 7-day sequences
for stock_code in stocks_to_process:
    dates = sorted(stock_data[stock_code])

    i = 0
    while i < len(dates):
        # Start a new sequence
        start_date_str = dates[i]
        start_date = datetime.strptime(start_date_str, '%Y%m%d').date()
        consecutive_count = 1

        # Count consecutive weeks (7-day apart)
        j = i + 1
        while j < len(dates):
            current_date_str = dates[j]
            current_date = datetime.strptime(current_date_str, '%Y%m%d').date()

            prev_date = datetime.strptime(dates[j-1], '%Y%m%d').date()

            # Check if 7 days apart (within range to account for weekends/holidays)
            days_diff = (current_date - prev_date).days
            if 5 <= days_diff <= 9:  # Allow range for weekends
                consecutive_count += 1
                j += 1
            else:
                break

        consecutive_sequences.append({
            'stock_code': stock_code,
            'start_date': start_date_str,
            'consecutive_weeks': consecutive_count,
            'end_date': dates[j-1]
        })

        i = j if j > i + 1 else i + 1

print(f"Found {len(consecutive_sequences)} consecutive sequences")

# Step 4: Get daily prices for forward return calculation
cur.execute("""
    SELECT stock_code, date, close_price
    FROM daily_prices
    ORDER BY stock_code, date
""")

price_data = cur.fetchall()
price_map = defaultdict(dict)  # price_map[stock_code][date] = close_price

for row in price_data:
    date_str = row['date']
    try:
        if len(date_str) == 8:  # YYYYMMDD format
            date_obj = datetime.strptime(date_str, '%Y%m%d').date()
        else:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        price_val = float(row['close_price']) if isinstance(row['close_price'], (int, float, str)) else float(row['close_price'])
        price_map[row['stock_code']][date_obj] = price_val
    except Exception as e:
        print(f"Error parsing date {date_str}: {e}")
        continue

print(f"Loaded price data for {len(price_map)} stocks")

# Step 5: Calculate forward returns
results = []

for seq in consecutive_sequences:
    stock_code = seq['stock_code']
    start_date_str = seq['start_date']
    consecutive_weeks = seq['consecutive_weeks']

    # Convert start date
    start_date = datetime.strptime(start_date_str, '%Y%m%d').date()

    # Get starting price (from daily_prices)
    if start_date not in price_map[stock_code]:
        # Find nearest date with price data
        available_dates = sorted(price_map[stock_code].keys())
        closest_date = None
        for d in available_dates:
            if d >= start_date:
                closest_date = d
                break
        if closest_date is None and available_dates:
            closest_date = available_dates[-1]

        if closest_date is None:
            continue
        start_date = closest_date

    start_price = price_map[stock_code][start_date]

    # 避免除以零
    if start_price == 0:
        continue

    # Calculate forward dates (1, 2, 4, 12 weeks)
    forward_weeks_list = [1, 2, 4, 12]

    for weeks_forward in forward_weeks_list:
        forward_date = start_date + timedelta(days=weeks_forward*7)

        # Find the nearest trading date
        forward_price = None
        available_dates = sorted(price_map[stock_code].keys())

        for d in sorted(available_dates):
            if d >= forward_date:
                forward_price = price_map[stock_code][d]
                break

        if forward_price is None:
            continue

        return_pct = ((forward_price - start_price) / start_price) * 100

        results.append({
            'stock_code': stock_code,
            'start_date': start_date_str,
            'consecutive_weeks': consecutive_weeks,
            'weeks_forward': weeks_forward,
            'start_price': start_price,
            'forward_price': forward_price,
            'return_pct': return_pct
        })

print(f"Calculated returns for {len(results)} forward cases")

# Step 6: Aggregate by consecutive weeks
df = pd.DataFrame(results)

if len(df) > 0:
    # Group by consecutive_weeks and weeks_forward
    grouped = df.groupby(['consecutive_weeks', 'weeks_forward']).agg({
        'return_pct': ['count', 'mean', 'median', 'min', 'max', 'std']
    }).round(2)

    print("\n" + "="*80)
    print("ANALYSIS RESULTS: ratio_400_above Consecutive Weeks vs Forward Returns")
    print("="*80 + "\n")
    print(grouped)

    # Also provide summary by consecutive_weeks
    print("\n" + "="*80)
    print("SUMMARY BY CONSECUTIVE WEEKS")
    print("="*80 + "\n")

    summary = df.groupby('consecutive_weeks').agg({
        'return_pct': ['count', 'mean', 'median', 'std'],
        'stock_code': 'nunique'
    }).round(2)
    summary.columns = ['Cases', 'Avg Return %', 'Median Return %', 'Std Dev %', 'Unique Stocks']
    print(summary)

    # Pivot table: consecutive weeks vs weeks forward
    print("\n" + "="*80)
    print("PIVOT TABLE: Average Return % by Consecutive Weeks and Forward Period")
    print("="*80 + "\n")

    pivot = df.pivot_table(
        values='return_pct',
        index='consecutive_weeks',
        columns='weeks_forward',
        aggfunc='mean'
    ).round(2)
    print(pivot)

    # Count pivot
    print("\n" + "="*80)
    print("CASE COUNT by Consecutive Weeks and Forward Period")
    print("="*80 + "\n")

    count_pivot = df.pivot_table(
        values='return_pct',
        index='consecutive_weeks',
        columns='weeks_forward',
        aggfunc='count'
    ).astype('Int64')
    print(count_pivot)

cur.close()
conn.close()

# 保存詳細結果
output_file = f'/home/tom/stock-verify/tdcc-whale-accumulation/ratio_400_consecutive_{agent_name}_{start_idx}_{end_idx}.csv'
df.to_csv(output_file, index=False)
print(f"\n✓ 結果已保存到 {output_file}")
print("\n✓ Analysis complete")
