"""
從 norway.twsthr.info 補爬所有 holdings 中一般股的歷史 TDCC 資料
（排除 ETF/特殊代碼，只爬 4-5 位數字且不以 00 開頭的股票）

用法:
    python3 crawl_norway_all.py
"""

import re
import sqlite3
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
BASE_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={}'

# 固定欄位索引（同 crawl_norway_history.py）
IDX_DATE    = 2
IDX_HOLDERS = 4
IDX_R400    = 7
IDX_R1000   = 13
IDX_PRICE   = 14


def get_target_stocks() -> list[str]:
    """取得需要補爬的一般股清單"""
    conn = sqlite3.connect(DB_PATH)
    all_stocks = {r[0] for r in conn.execute('SELECT DISTINCT stock_code FROM holdings').fetchall()}
    pre2025 = {r[0] for r in conn.execute(
        'SELECT DISTINCT stock_code FROM holdings WHERE date < 20250101'
    ).fetchall()}
    conn.close()
    need = sorted(all_stocks - pre2025)
    # 只保留 4-5 位數字，不以 00 開頭
    return [c for c in need if re.match(r'^\d{4,5}$', c) and not c.startswith('00')]


def fetch_stock(code: str) -> list[dict]:
    url = BASE_URL.format(code)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    target_table = soup.find('table', {'id': 'Details'})
    if target_table is None:
        return []

    rows = target_table.find_all('tr')
    if len(rows) < 2:
        return []

    records = []
    for row in rows[1:]:
        cols = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cols) <= max(IDX_DATE, IDX_R400, IDX_R1000, IDX_HOLDERS, IDX_PRICE):
            continue
        date_val = cols[IDX_DATE].replace('/', '').replace('-', '')
        if not date_val.isdigit() or len(date_val) != 8:
            continue
        try:
            r400    = float(cols[IDX_R400].replace(',', ''))
            r1000   = float(cols[IDX_R1000].replace(',', ''))
            holders = int(cols[IDX_HOLDERS].replace(',', ''))
            price   = float(cols[IDX_PRICE].replace(',', ''))
        except (ValueError, IndexError):
            continue
        records.append({
            'stock_code': code, 'date': date_val,
            'ratio_400_above': r400, 'ratio_1000_above': r1000,
            'total_holders': holders, 'close_price': price,
        })
    return records


def save_to_db(records: list[dict]) -> tuple[int, int]:
    if not records:
        return 0, 0
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    c = conn.cursor()
    inserted = skipped = 0
    for rec in records:
        c.execute('''
            INSERT OR IGNORE INTO holdings (stock_code, date, ratio_400_above, ratio_1000_above, total_holders)
            VALUES (?, ?, ?, ?, ?)
        ''', (rec['stock_code'], rec['date'], rec['ratio_400_above'],
              rec['ratio_1000_above'], rec['total_holders']))
        if c.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
        c.execute('''
            INSERT OR IGNORE INTO daily_prices (stock_code, date, close_price)
            VALUES (?, ?, ?)
        ''', (rec['stock_code'], rec['date'], rec['close_price']))
    conn.commit()
    conn.close()
    return inserted, skipped


def main():
    targets = get_target_stocks()
    print(f'待爬股票: {len(targets)} 檔')
    print(f'預估時間: {len(targets) * 0.9 / 60:.0f} 分鐘\n')

    total_new = 0
    fail_count = 0

    for i, code in enumerate(targets, 1):
        records = fetch_stock(code)
        if not records:
            fail_count += 1
            if i % 100 == 0:
                print(f'[{i:4d}/{len(targets)}] {code} 無資料 (累計失敗 {fail_count})', flush=True)
            time.sleep(0.5)
            continue

        new_cnt, _ = save_to_db(records)
        total_new += new_cnt
        dates = [r['date'] for r in records]

        if i % 100 == 0 or new_cnt > 0 and i <= 20:
            print(f'[{i:4d}/{len(targets)}] {code} '
                  f'| {len(records)} 週 ({min(dates)}~{max(dates)}) '
                  f'| +{new_cnt} 筆 | 累計新增: {total_new:,}', flush=True)

        time.sleep(0.8)

    print(f'\n完成！總計新增 {total_new:,} 筆 holdings 資料，失敗 {fail_count} 檔')

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT COUNT(*), COUNT(DISTINCT stock_code), MIN(date), MAX(date) FROM holdings'
    ).fetchone()
    print(f'Holdings 總計: {row[0]:,} 筆 | {row[1]} 檔 | {row[2]} ~ {row[3]}')

    row2 = conn.execute(
        'SELECT COUNT(DISTINCT stock_code) FROM holdings WHERE date < 20250101'
    ).fetchone()
    print(f'2022-2024 涵蓋: {row2[0]} 檔')
    conn.close()


if __name__ == '__main__':
    main()
