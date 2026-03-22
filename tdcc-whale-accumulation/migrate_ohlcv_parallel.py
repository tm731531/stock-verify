#!/usr/bin/env python3
"""
並行補齊 PostgreSQL daily_prices 的開高收低量
用多進程加速：每個進程處理不同的月份
"""

import psycopg2
import requests
import sys
from multiprocessing import Pool, Queue
from datetime import datetime
from collections import defaultdict
import time

DB_CONN = "host=localhost port=5432 dbname=tdcc user=tdcc password=tdcc1234"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
REQUEST_TIMEOUT = 20
NUM_WORKERS = 8  # 8 個並行進程

def _roc_to_western(roc_date: str) -> str:
    """Convert ROC date YYY/MM/DD to YYYYMMDD."""
    parts = roc_date.strip().split("/")
    y = int(parts[0]) + 1911
    return f"{y}{parts[1]}{parts[2]}"

def fetch_twse_month(stock_code: str, year_month: str):
    """從 TWSE 拿一檔股票一個月的開高收低量"""
    try:
        date_param = f"{year_month}01"
        resp = requests.get(
            TWSE_STOCK_DAY_URL,
            params={"response": "json", "date": date_param, "stockNo": stock_code},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("stat") != "OK":
            return {}

        result = {}
        for row in data.get("data", []):
            try:
                western_date = _roc_to_western(row[0])
                open_str = row[3].replace(",", "").strip()
                high_str = row[4].replace(",", "").strip()
                low_str = row[5].replace(",", "").strip()
                volume_str = row[1].replace(",", "").strip()

                open_price = float(open_str) if open_str else None
                high_price = float(high_str) if high_str else None
                low_price = float(low_str) if low_str else None
                volume = int(volume_str) if volume_str and volume_str.isdigit() else None

                result[western_date] = {
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'volume': volume
                }
            except (ValueError, IndexError):
                continue

        return result

    except Exception as e:
        return {}

def process_month(month_data):
    """處理一個月份的所有股票（在工作進程中執行）"""
    month, codes = month_data

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    updated = 0
    for code in codes:
        ohlcv = fetch_twse_month(code, month)

        if not ohlcv:
            continue

        # 批量更新
        for date, data in ohlcv.items():
            cursor.execute(
                "UPDATE daily_prices SET open_price=%s, high_price=%s, low_price=%s, volume=%s WHERE stock_code=%s AND date=%s",
                (data['open'], data['high'], data['low'], data['volume'], code, date)
            )
            if cursor.rowcount > 0:
                updated += 1

        conn.commit()
        time.sleep(0.1)  # 輕量級延遲

    conn.close()
    return (month, len(codes), updated)

def main():
    print("="*60)
    print(f"並行補齊 PostgreSQL 開高收低量 ({NUM_WORKERS} 進程)")
    print("="*60)

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    # 查詢缺少 open_price 的記錄
    cursor.execute("""
        SELECT DISTINCT stock_code, date
        FROM daily_prices
        WHERE close_price IS NOT NULL
          AND open_price IS NULL
        ORDER BY date, stock_code
    """)
    missing = cursor.fetchall()
    print(f"\n需補齊的 (stock, date) 組合：{len(missing):,} 筆")

    if not missing:
        print("✓ 已全部補齊！")
        conn.close()
        return

    # 按月份分組
    by_month = defaultdict(set)
    for code, date in missing:
        month = date[:6]
        by_month[month].add(code)

    months_list = [(month, sorted(codes)) for month, codes in sorted(by_month.items())]
    print(f"涉及 {len(months_list)} 個月份\n")

    # 多進程處理
    with Pool(processes=NUM_WORKERS) as pool:
        results = pool.imap_unordered(process_month, months_list)

        completed = 0
        total_updated = 0
        for month, num_codes, updated in results:
            completed += 1
            total_updated += updated
            print(f"[{completed}/{len(months_list)}] {month}: {num_codes} 檔, 更新 {updated:,} 筆")

    print(f"\n✅ 並行處理完成！")
    print(f"   總更新筆數：{total_updated:,}")

    # 最終統計
    cursor.execute("""
        SELECT COUNT(*) as 總筆,
               COUNT(CASE WHEN open_price IS NOT NULL THEN 1 END) as 有open,
               COUNT(CASE WHEN high_price IS NOT NULL THEN 1 END) as 有high,
               COUNT(CASE WHEN low_price IS NOT NULL THEN 1 END) as 有low,
               COUNT(CASE WHEN volume IS NOT NULL THEN 1 END) as 有volume
        FROM daily_prices
    """)
    stats = cursor.fetchone()
    conn.close()

    print(f"\n📊 最終統計：")
    print(f"   總筆數：{stats[0]:,}")
    print(f"   有 open_price：{stats[1]:,}")
    print(f"   有 high_price：{stats[2]:,}")
    print(f"   有 low_price：{stats[3]:,}")
    print(f"   有 volume：{stats[4]:,}")

if __name__ == "__main__":
    main()
