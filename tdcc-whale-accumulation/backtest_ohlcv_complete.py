#!/usr/bin/env python3
"""
TDCC 鯨魚策略 v7 完整回測 - 用開高收低 (OHLCV)

用日內邏輯（開高收低）進行回測：
- 進場：檢查 low_price ≤ limit_price
- 停損：檢查 low_price 觸及 -7%
- 停利：檢查 high_price 達 +15%，low_price 回落 10%
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict
from pathlib import Path

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

print("="*80)
print("TDCC 鯨魚策略 v7 完整回測 - 用完整 OHLCV 資料")
print("="*80)

CAPITAL = 500_000
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

print("\n加載數據...")

# 日期
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
    ORDER BY date
""")
all_dates = [r['date'] for r in cursor.fetchall()]
date_to_idx = {d: i for i, d in enumerate(all_dates)}

# 價格 - 加載完整 OHLCV
cursor.execute("""
    SELECT stock_code, date, open_price, high_price, low_price, close_price
    FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
""")
prices = defaultdict(lambda: defaultdict(dict))
for r in cursor.fetchall():
    code = r['stock_code']
    date = r['date']
    # 確保都轉成 float，防止 Decimal 型別問題
    prices[code][date] = {
        'open': float(r['open_price']) if r['open_price'] else None,
        'high': float(r['high_price']) if r['high_price'] else None,
        'low': float(r['low_price']) if r['low_price'] else None,
        'close': float(r['close_price']) if r['close_price'] else None,
    }

# TDCC 數據
cursor.execute("""
    SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    ORDER BY stock_code, date
""")
tdcc_data = defaultdict(list)
for r in cursor.fetchall():
    tdcc_data[r['stock_code']].append(r)

print(f"✓ {len(all_dates)} 個交易日")
print(f"✓ {len(prices)} 支股票有價格數據")
print(f"✓ {len(tdcc_data)} 支股票有 TDCC 數據")

# 統計 OHLCV 完整性
ohlcv_complete = 0
close_only = 0
for code in prices:
    for date in prices[code]:
        if prices[code][date].get('open') is not None:
            ohlcv_complete += 1
        else:
            close_only += 1

print(f"✓ 完整 OHLCV：{ohlcv_complete:,} 筆")
print(f"✓ 僅有收盤價：{close_only:,} 筆")

# ================================================================================
# 簡化版信號掃描 (沿用舊邏輯)
# ================================================================================

print("\n掃描信號...")

# 這裡應該用原始的複雜信號掃描邏輯
# 為了快速測試，先用簡化版本
main_sigs = []
backup_sigs = []

print(f"✓ 主引擎：{len(main_sigs)} 個")
print(f"✓ 備位引擎：{len(backup_sigs)} 個")
print("⚠️  注意：信號掃描已簡化，需補充完整邏輯")

# ================================================================================
# 提示用戶需要補充完整邏輯
# ================================================================================

print("\n" + "="*80)
print("⚠️  提示")
print("="*80)
print("""
為了執行完整回測，需要：
1. 複製原始信號掃描邏輯（scan_all_signals）
2. 複製完整的回測引擎（run_backtest）
3. 在出場邏輯中改用開高收低進行日內判斷

目前這個版本展示了如何加載和轉換 OHLCV 資料。

建議方案：
- 複製 backtest_complete_final.py 的全部信號掃描邏輯
- 改出場檢查部分，加入開高收低邏輯
""")

conn.close()
