#!/usr/bin/env python3
"""
快速補齊 PostgreSQL daily_prices 的開高收低量
策略：只查詢已有 close_price 的日期/股票組合
直接從 TWSE API 拿開高收低，批量更新 PG
"""

import psycopg2
import requests
import sys
from datetime import datetime
from collections import defaultdict
import time

DB_CONN = "host=localhost port=5432 dbname=tdcc user=tdcc password=tdcc1234"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.5

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

        # fields: 日期(ROC), 成交股數(idx 1), 成交金額, 開盤價(3), 最高價(4), 最低價(5), 收盤價(6)...
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
        print(f"  ✗ {stock_code} {year_month}: {e}")
        return {}

def main():
    print("="*60)
    print("快速補齊 PostgreSQL 開高收低量")
    print("="*60)

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    # 查詢哪些 (stock, date) 有 close_price 但缺少 open_price
    cursor.execute("""
        SELECT DISTINCT stock_code, date
        FROM daily_prices
        WHERE close_price IS NOT NULL
          AND open_price IS NULL
        ORDER BY stock_code, date
    """)
    missing = cursor.fetchall()
    print(f"\n需補齊的 (stock, date) 組合：{len(missing):,} 筆")

    if not missing:
        print("✓ 已全部補齊！")
        conn.close()
        return

    # 按月份分組（減少 API 呼叫）
    by_month = defaultdict(list)
    for code, date in missing:
        month = date[:6]  # YYYYMM
        by_month[month].append((code, date))

    print(f"涉及 {len(by_month)} 個月份")
    print()

    # 遍歷月份，補齊該月所有股票的開高收低
    total_months = len(by_month)
    processed_months = 0
    updated_rows = 0

    for month in sorted(by_month.keys()):
        processed_months += 1
        codes_in_month = set(code for code, _ in by_month[month])

        print(f"[{processed_months}/{total_months}] {month}: {len(codes_in_month)} 檔", end=" ")
        sys.stdout.flush()

        for code in sorted(codes_in_month):
            ohlcv = fetch_twse_month(code, month)

            if not ohlcv:
                continue

            # 批量更新該股票該月的開高收低
            updates = [
                (ohlcv[date]['open'], ohlcv[date]['high'], ohlcv[date]['low'], ohlcv[date]['volume'], code, date)
                for date in ohlcv
                if date in [d for c, d in by_month[month] if c == code]
            ]

            if updates:
                cursor.executemany(
                    "UPDATE daily_prices SET open_price=%s, high_price=%s, low_price=%s, volume=%s WHERE stock_code=%s AND date=%s",
                    updates
                )
                updated_rows += len(updates)
                conn.commit()

            time.sleep(REQUEST_DELAY)

        print(f"✓ {len(codes_in_month)} 檔補齊")

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

    print(f"\n✅ 完成！")
    print(f"   更新筆數：{updated_rows:,}")
    print(f"\n📊 最終統計：")
    print(f"   總筆數：{stats[0]:,}")
    print(f"   有 open_price：{stats[1]:,}")
    print(f"   有 high_price：{stats[2]:,}")
    print(f"   有 low_price：{stats[3]:,}")
    print(f"   有 volume：{stats[4]:,}")

if __name__ == "__main__":
    main()
