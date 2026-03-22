#!/usr/bin/env python3
"""
Upgrade SQLite daily_prices table to include open/high/low/volume.
If table exists but lacks columns, adds them.
If table is incomplete, migrates data from old table.
"""

import sqlite3
from pathlib import Path

SQLITE_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

def upgrade_schema():
    conn = sqlite3.connect(SQLITE_PATH, timeout=30)
    cur = conn.cursor()

    # 檢查表是否存在
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_prices'")
    table_exists = cur.fetchone() is not None

    if not table_exists:
        print("✓ daily_prices 表不存在，將由爬蟲程式自動建立")
        conn.close()
        return

    # 檢查現有欄位
    cur.execute("PRAGMA table_info(daily_prices)")
    columns = {row[1] for row in cur.fetchall()}
    print(f"現有欄位: {columns}")

    required_columns = {'stock_code', 'date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume'}
    missing_columns = required_columns - columns

    if not missing_columns:
        print("✓ 表結構已完整，無需修改")
        conn.close()
        return

    print(f"缺少欄位: {missing_columns}")

    # 備份舊表
    print("→ 備份舊表...")
    cur.execute("ALTER TABLE daily_prices RENAME TO daily_prices_old")
    conn.commit()

    # 建立新表（帶完整欄位）
    print("→ 建立新表...")
    cur.execute("""
        CREATE TABLE daily_prices (
            stock_code TEXT NOT NULL,
            date TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL NOT NULL,
            volume INTEGER,
            PRIMARY KEY (stock_code, date)
        )
    """)

    # 遷移舊數據
    print("→ 遷移數據...")
    cur.execute("""
        INSERT INTO daily_prices (stock_code, date, close_price)
        SELECT stock_code, date, close_price
        FROM daily_prices_old
    """)
    migrated = cur.rowcount
    print(f"  已遷移 {migrated:,} 筆數據")

    conn.commit()

    # 刪除舊表
    print("→ 清理舊表...")
    cur.execute("DROP TABLE daily_prices_old")
    conn.commit()

    # 統計
    cur.execute("SELECT COUNT(*) FROM daily_prices")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM daily_prices WHERE open_price IS NOT NULL")
    complete = cur.fetchone()[0]

    print(f"\n✅ 升級完成！")
    print(f"   總筆數: {total:,}")
    print(f"   完整欄位: {complete:,} 筆（需重新爬蟲補齊）")

    conn.close()

if __name__ == '__main__':
    upgrade_schema()
