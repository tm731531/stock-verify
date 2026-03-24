"""
補抓所有 holdings 股票的 2022~2024 日收盤價
策略：每天兩個批次請求
  - TWSE MI_INDEX: 一次取得所有上市股 (~1180檔)
  - TPEX batch:    一次取得所有上櫃股 (~800檔)

用法:
    python3 crawl_all_prices.py
"""

import sqlite3
import time
import requests
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'
START_DATE = '20220101'
END_DATE   = '20241231'

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
TWSE_MI_INDEX_URL = 'https://www.twse.com.tw/exchangeReport/MI_INDEX'
TPEX_BATCH_URL    = 'https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php'


def to_roc(yyyymmdd: str) -> str:
    y = int(yyyymmdd[:4]) - 1911
    return f'{y}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}'


def fetch_twse_day(date: str) -> dict[str, float]:
    """TWSE MI_INDEX: 全市場當日收盤"""
    try:
        r = requests.get(TWSE_MI_INDEX_URL,
                         params={'response': 'json', 'date': date, 'type': 'ALLBUT0999'},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get('stat') != 'OK':
            return {}
        # 找 >500 rows 的 table (所有股票那張)
        for table in data.get('tables', []):
            rows = table.get('data', [])
            if len(rows) > 500:
                prices = {}
                for row in rows:
                    code = row[0].strip()
                    try:
                        close = float(row[8].replace(',', '').strip())
                        prices[code] = close
                    except (ValueError, IndexError):
                        continue
                return prices
        return {}
    except Exception as e:
        return {}


def fetch_tpex_day(date: str) -> dict[str, float]:
    """TPEX 全市場當日收盤"""
    try:
        roc = to_roc(date)
        r = requests.get(TPEX_BATCH_URL,
                         params={'l': 'zh-tw', 'd': roc, 'se': 'EW', 'o': 'json'},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        # 驗證日期
        resp_roc = ''
        for t in data.get('tables', []):
            resp_roc = t.get('date', '')
            break
        if resp_roc and resp_roc != roc:
            return {}  # 假日
        prices = {}
        for table in data.get('tables', []):
            for row in table.get('data', []):
                code = row[0].strip()
                try:
                    close = float(row[2].replace(',', '').strip())
                    prices[code] = close
                except (ValueError, IndexError):
                    continue
        return prices
    except Exception:
        return {}


def get_covered_dates() -> set[str]:
    """已有 ≥ 1500 股資料的日期（代表 TWSE+TPEX 都抓了）"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('''
        SELECT date, COUNT(*) as n
        FROM daily_prices
        WHERE date >= ? AND date <= ?
        GROUP BY date HAVING n >= 1500
    ''', (START_DATE, END_DATE)).fetchall()
    conn.close()
    return {r[0] for r in rows}


def save_batch(date: str, prices: dict[str, float]):
    if not prices:
        return 0
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    records = [(code, date, p) for code, p in prices.items()]
    conn.executemany(
        'INSERT OR IGNORE INTO daily_prices (stock_code, date, close_price) VALUES (?,?,?)',
        records
    )
    n = conn.total_changes
    conn.commit()
    conn.close()
    return n


def main():
    bdays = [d.strftime('%Y%m%d')
             for d in pd.bdate_range(start=START_DATE, end=END_DATE)]
    print(f'日期範圍: {START_DATE} ~ {END_DATE}  ({len(bdays)} 個工作日)')

    covered = get_covered_dates()
    need = [d for d in bdays if d not in covered]
    print(f'已完成: {len(covered)} 天 | 待抓: {len(need)} 天\n')

    total_new = 0
    twse_ok = 0
    tpex_ok = 0

    for i, date in enumerate(need, 1):
        # TWSE
        twse = fetch_twse_day(date)
        n1 = save_batch(date, twse)
        if twse:
            twse_ok += 1

        time.sleep(0.3)

        # TPEX
        tpex = fetch_tpex_day(date)
        n2 = save_batch(date, tpex)
        if tpex:
            tpex_ok += 1

        total_new += n1 + n2
        time.sleep(0.3)

        if i % 50 == 0 or i == len(need):
            print(f'  [{i:4d}/{len(need)}] {date} | '
                  f'TWSE: {len(twse):4d}  TPEX: {len(tpex):4d} | '
                  f'累計新增: {total_new:,}', flush=True)

    print(f'\n完成！新增 {total_new:,} 筆  (TWSE: {twse_ok}天, TPEX: {tpex_ok}天)')

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT COUNT(*), COUNT(DISTINCT stock_code), MIN(date), MAX(date) '
        'FROM daily_prices WHERE date >= ? AND date <= ?',
        (START_DATE, END_DATE)
    ).fetchone()
    conn.close()
    print(f'DB 2022-2024: {row[0]:,} 筆 | {row[1]} 檔股票 | {row[2]} ~ {row[3]}')


if __name__ == '__main__':
    main()
