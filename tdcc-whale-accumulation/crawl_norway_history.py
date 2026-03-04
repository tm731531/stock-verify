"""
從 norway.twsthr.info 爬取 26 檔訊號股票的完整歷史 TDCC 數據（2011~今）
並補入現有 SQLite 資料庫（不覆蓋已有資料）

用法:
    python3 crawl_norway_history.py
"""

import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

# 26 檔出現在策略訊號中的股票
TARGET_STOCKS = [
    '1519', '1560', '1795', '2357', '2382', '3008', '3017', '3131',
    '3324', '3406', '3413', '3443', '3563', '4728', '4749', '5289',
    '5536', '6223', '6274', '6446', '6488', '6510', '6515', '6531',
    '6919', '8210',
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
BASE_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={}'


def fetch_stock(code: str) -> list[dict]:
    """爬取單一股票的完整歷史數據"""
    url = BASE_URL.format(code)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f'  [{code}] 請求失敗: {e}')
        return []

    soup = BeautifulSoup(r.text, 'html.parser')

    # 直接用 id=Details (大寫 D) 定位主要數據表格
    target_table = soup.find('table', {'id': 'Details'})
    if target_table is None:
        print(f'  [{code}] 找不到 id=Details 表格')
        return []

    rows = target_table.find_all('tr')
    if len(rows) < 2:
        print(f'  [{code}] 表格資料不足')
        return []

    # 固定欄位索引（已確認）
    idx_date    = 2   # 資料日期
    idx_holders = 4   # 總股東人數
    idx_r400    = 7   # >400張大股東持有百分比
    idx_r1000   = 13  # >1000張大股東持有百分比
    idx_price   = 14  # 收盤價

    records = []
    for row in rows[1:]:
        cols = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cols) <= max(idx_date, idx_r400, idx_r1000, idx_holders, idx_price):
            continue

        date_val = cols[idx_date].replace('/', '').replace('-', '')
        if not date_val.isdigit() or len(date_val) != 8:
            continue

        try:
            r400  = float(cols[idx_r400].replace(',', ''))
            r1000 = float(cols[idx_r1000].replace(',', ''))
            holders = int(cols[idx_holders].replace(',', ''))
            price = float(cols[idx_price].replace(',', ''))
        except (ValueError, IndexError):
            continue

        records.append({
            'stock_code': code,
            'date': date_val,
            'ratio_400_above': r400,
            'ratio_1000_above': r1000,
            'total_holders': holders,
            'close_price': price,
        })

    return records


def save_to_db(records: list[dict]) -> tuple[int, int]:
    """儲存至 SQLite，回傳 (新增筆數, 跳過筆數)"""
    if not records:
        return 0, 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    inserted = 0
    skipped = 0

    for rec in records:
        # holdings 表
        try:
            c.execute('''
                INSERT OR IGNORE INTO holdings (stock_code, date, ratio_400_above, ratio_1000_above, total_holders)
                VALUES (?, ?, ?, ?, ?)
            ''', (rec['stock_code'], rec['date'], rec['ratio_400_above'],
                  rec['ratio_1000_above'], rec['total_holders']))
            if c.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            pass

        # daily_prices 表
        try:
            c.execute('''
                INSERT OR IGNORE INTO daily_prices (stock_code, date, close_price)
                VALUES (?, ?, ?)
            ''', (rec['stock_code'], rec['date'], rec['close_price']))
        except Exception:
            pass

    conn.commit()
    conn.close()
    return inserted, skipped


def check_existing(code: str) -> tuple[int, str, str]:
    """查詢目前 DB 中該股票有多少週數據"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT COUNT(*), MIN(date), MAX(date) FROM holdings WHERE stock_code=?
    ''', (code,))
    row = c.fetchone()
    conn.close()
    return row[0], row[1] or '', row[2] or ''


def main():
    print(f'目標: {len(TARGET_STOCKS)} 檔股票')
    print(f'資料庫: {DB_PATH}')
    print()

    total_new = 0
    total_skip = 0

    for i, code in enumerate(TARGET_STOCKS, 1):
        existing, d_min, d_max = check_existing(code)
        print(f'[{i:02d}/{len(TARGET_STOCKS)}] {code} | DB現有: {existing}週 ({d_min}~{d_max})')

        records = fetch_stock(code)
        if not records:
            print(f'  → 爬取失敗，跳過')
            time.sleep(1)
            continue

        new_cnt, skip_cnt = save_to_db(records)
        total_new += new_cnt
        total_skip += skip_cnt

        dates = [r['date'] for r in records]
        print(f'  → 爬到 {len(records)} 週 ({min(dates)}~{max(dates)})，新增 {new_cnt}，跳過(已有) {skip_cnt}')
        time.sleep(0.8)  # 友善延遲

    print()
    print(f'完成！總計新增 {total_new} 筆，跳過(重複) {total_skip} 筆')


if __name__ == '__main__':
    main()
