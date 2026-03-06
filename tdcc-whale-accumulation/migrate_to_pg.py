"""
SQLite → PostgreSQL 遷移腳本
============================
建立 tdcc 資料庫，daily_prices 用 RANGE PARTITION by year，
再從 SQLite 批次匯入所有資料。

用法:
  python3 migrate_to_pg.py
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from pathlib import Path

SQLITE_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

# PG 連線（以 postgres 超級使用者建資料庫）
PG_ADMIN = dict(host='localhost', port=5432, dbname='postgres',
                user='postgres', password='')

# 新建的資料庫 + 應用帳號
DB_NAME   = 'tdcc'
DB_USER   = 'tdcc'
DB_PASS   = 'tdcc1234'

BATCH     = 50_000


# ─────────────────────────────────────────────
# 1. 建立資料庫與使用者
# ─────────────────────────────────────────────

def create_db():
    conn = psycopg2.connect(**PG_ADMIN)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(f"SELECT 1 FROM pg_roles WHERE rolname='{DB_USER}'")
    if not cur.fetchone():
        cur.execute(f"CREATE USER {DB_USER} WITH PASSWORD '{DB_PASS}'")
        print(f'✅ 建立使用者 {DB_USER}')

    cur.execute(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER} ENCODING 'UTF8'")
        print(f'✅ 建立資料庫 {DB_NAME}')
    else:
        print(f'ℹ️  資料庫 {DB_NAME} 已存在')

    cur.close()
    conn.close()


# ─────────────────────────────────────────────
# 2. 建立 Schema（含 Partition）
# ─────────────────────────────────────────────

def create_schema():
    conn = psycopg2.connect(host='localhost', port=5432, dbname=DB_NAME,
                            user='postgres', password='')
    conn.autocommit = True
    cur = conn.cursor()

    # holdings（不分區，33萬筆，查詢夠快）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            stock_code       VARCHAR(10) NOT NULL,
            date             VARCHAR(8)  NOT NULL,
            ratio_400_above  NUMERIC(8,2),
            ratio_1000_above NUMERIC(8,2),
            total_holders    INTEGER,
            PRIMARY KEY (stock_code, date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_holdings_date ON holdings(date)")
    print('✅ 建立 holdings')

    # daily_prices：RANGE PARTITION by year（date 為 YYYYMMDD 字串，字典序=時間序）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            stock_code  VARCHAR(10) NOT NULL,
            date        VARCHAR(8)  NOT NULL,
            close_price NUMERIC(12,2),
            PRIMARY KEY (stock_code, date)
        ) PARTITION BY RANGE (date)
    """)

    # 每年一個 partition（涵蓋現有資料 + 預留到 2030）
    for yr in range(2017, 2031):
        pname = f'daily_prices_{yr}'
        lo = f'{yr}0101'
        hi = f'{yr+1}0101'
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {pname}
            PARTITION OF daily_prices
            FOR VALUES FROM ('{lo}') TO ('{hi}')
        """)

    # 預設 partition（抓住所有不在年份範圍內的奇異資料）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices_default
        PARTITION OF daily_prices DEFAULT
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_dp_date ON daily_prices(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dp_code ON daily_prices(stock_code)")
    print('✅ 建立 daily_prices（RANGE PARTITION by year，2017-2030 + default）')

    # 授權
    cur.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {DB_USER}")
    cur.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {DB_USER}")
    print(f'✅ 授權 {DB_USER}')

    cur.close()
    conn.close()


# ─────────────────────────────────────────────
# 3. 遷移資料
# ─────────────────────────────────────────────

def migrate_holdings(sqlite_conn, pg_conn):
    cur_s = sqlite_conn.cursor()
    cur_p = pg_conn.cursor()

    # 確認目標是否已有資料
    cur_p.execute('SELECT COUNT(*) FROM holdings')
    existing = cur_p.fetchone()[0]
    if existing > 0:
        print(f'ℹ️  holdings 已有 {existing:,} 筆，略過（--force 可強制重寫）')
        return

    total = sqlite_conn.execute('SELECT COUNT(*) FROM holdings').fetchone()[0]
    print(f'遷移 holdings（{total:,} 筆）...')

    offset = 0
    written = 0
    while True:
        rows = cur_s.execute(
            'SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders '
            'FROM holdings ORDER BY stock_code, date '
            f'LIMIT {BATCH} OFFSET {offset}'
        ).fetchall()
        if not rows:
            break
        execute_values(cur_p,
            'INSERT INTO holdings VALUES %s ON CONFLICT DO NOTHING', rows)
        pg_conn.commit()
        written += len(rows)
        offset  += BATCH
        print(f'  {written:,} / {total:,}', end='\r', flush=True)

    print(f'\n✅ holdings 遷移完成：{written:,} 筆')


def migrate_daily_prices(sqlite_conn, pg_conn):
    cur_s = sqlite_conn.cursor()
    cur_p = pg_conn.cursor()

    cur_p.execute('SELECT COUNT(*) FROM daily_prices')
    existing = cur_p.fetchone()[0]
    if existing > 0:
        print(f'ℹ️  daily_prices 已有 {existing:,} 筆，略過（--force 可強制重寫）')
        return

    total = sqlite_conn.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0]
    print(f'遷移 daily_prices（{total:,} 筆）...')

    offset = 0
    written = 0
    while True:
        rows = cur_s.execute(
            'SELECT stock_code, date, close_price '
            'FROM daily_prices ORDER BY date, stock_code '
            f'LIMIT {BATCH} OFFSET {offset}'
        ).fetchall()
        if not rows:
            break
        execute_values(cur_p,
            'INSERT INTO daily_prices VALUES %s ON CONFLICT DO NOTHING', rows)
        pg_conn.commit()
        written += len(rows)
        offset  += BATCH
        print(f'  {written:,} / {total:,}', end='\r', flush=True)

    print(f'\n✅ daily_prices 遷移完成：{written:,} 筆')


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

def main():
    print('=== SQLite → PostgreSQL 遷移 ===\n')

    print('─ 步驟 1：建立 DB / 使用者')
    create_db()

    print('\n─ 步驟 2：建立 Schema')
    create_schema()

    print('\n─ 步驟 3：遷移資料')
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = psycopg2.connect(
        host='localhost', port=5432, dbname=DB_NAME,
        user='postgres', password=''
    )

    migrate_holdings(sqlite_conn, pg_conn)
    migrate_daily_prices(sqlite_conn, pg_conn)

    sqlite_conn.close()
    pg_conn.close()

    # 最終確認
    pg_conn = psycopg2.connect(host='localhost', port=5432, dbname=DB_NAME,
                               user=DB_USER, password=DB_PASS)
    cur = pg_conn.cursor()
    cur.execute('SELECT COUNT(*) FROM holdings')
    h = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM daily_prices')
    d = cur.fetchone()[0]
    print(f'\n📊 最終確認（以 {DB_USER} 帳號連線）')
    print(f'  holdings:     {h:,} 筆')
    print(f'  daily_prices: {d:,} 筆')
    pg_conn.close()

    print(f'\n🎉 完成！')
    print(f'   Host: localhost:5432')
    print(f'   DB:   {DB_NAME}')
    print(f'   User: {DB_USER} / {DB_PASS}')


if __name__ == '__main__':
    main()
