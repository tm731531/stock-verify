"""
補抓 26 檔訊號股票的 2022~2024 日收盤價
使用官方 API：TWSE STOCK_DAY (上市) + TPEX st43 (上櫃)
不覆蓋已有資料。

用法:
    python3 crawl_daily_prices.py
"""

import sqlite3
import time
import requests
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

TARGET_STOCKS = [
    '1519', '1560', '1795', '2357', '2382', '3008', '3017', '3131',
    '3324', '3406', '3413', '3443', '3563', '4728', '4749', '5289',
    '5536', '6223', '6274', '6446', '6488', '6510', '6515', '6531',
    '6919', '8210',
]

# 月份範圍：2022/01 ~ 2024/12
START_MONTH = '202201'
END_MONTH   = '202412'

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
TWSE_STOCK_DAY_URL      = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY'
TWSE_STOCK_DAY_ALL_URL  = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL'
TPEX_BATCH_URL          = 'https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php'


def gen_months(start: str, end: str) -> list[str]:
    """產生 YYYYMM 月份清單"""
    months = []
    cur = pd.Timestamp(start + '01')
    fin = pd.Timestamp(end + '01')
    while cur <= fin:
        months.append(cur.strftime('%Y%m'))
        cur += pd.offsets.MonthBegin(1)
    return months


def roc_to_western(roc_date: str) -> str:
    parts = roc_date.strip().split('/')
    return f'{int(parts[0]) + 1911}{parts[1]}{parts[2]}'


def get_twse_stocks() -> set[str]:
    """取得目前所有 TWSE 上市股票代碼"""
    try:
        r = requests.get(TWSE_STOCK_DAY_ALL_URL, params={'response': 'json'},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        return {row[0].strip() for row in data.get('data', [])}
    except Exception as e:
        print(f'  無法取得 TWSE 股票清單: {e}')
        return set()


def fetch_twse_month(code: str, ym: str) -> list[tuple]:
    """從 TWSE STOCK_DAY 取得單一股票單月日收盤 (上市)"""
    try:
        r = requests.get(TWSE_STOCK_DAY_URL,
                         params={'response': 'json', 'date': ym + '01', 'stockNo': code},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        if data.get('stat') != 'OK':
            return []
        records = []
        for row in data.get('data', []):
            try:
                date = roc_to_western(row[0])
                close = float(row[6].replace(',', '').strip())
                records.append((code, date, close))
            except (ValueError, IndexError):
                continue
        return records
    except Exception as e:
        print(f'    TWSE {code} {ym}: {e}')
        return []


def fetch_tpex_day(date_yyyymmdd: str, target_codes: set[str]) -> list[tuple]:
    """從 TPEX 批次 API 取得指定日期所有上櫃股收盤，回傳目標股的資料"""
    try:
        y = int(date_yyyymmdd[:4]) - 1911
        m = date_yyyymmdd[4:6]
        d = date_yyyymmdd[6:8]
        roc_date = f'{y}/{m}/{d}'
        r = requests.get(TPEX_BATCH_URL,
                         params={'l': 'zh-tw', 'd': roc_date, 'se': 'EW', 'o': 'json'},
                         headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        # 驗證日期
        resp_roc = data.get('tables', [{}])[0].get('date', '') if data.get('tables') else ''
        if resp_roc and resp_roc != roc_date:
            return []  # 日期不符（假日或非交易日）

        records = []
        for table in data.get('tables', []):
            for row in table.get('data', []):
                code = row[0].strip()
                if code not in target_codes:
                    continue
                try:
                    close = float(row[2].replace(',', '').strip())
                    records.append((code, date_yyyymmdd, close))
                except (ValueError, IndexError):
                    continue
        return records
    except Exception as e:
        return []


def get_existing_months(code: str) -> set[str]:
    """取得該股票在 daily_prices 中已有 ≥15 天資料的月份"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT date FROM daily_prices WHERE stock_code=? AND date < 20250101',
        (code,)
    ).fetchall()
    conn.close()
    from collections import Counter
    month_counts = Counter(r[0][:6] for r in rows)
    return {m for m, cnt in month_counts.items() if cnt >= 15}


def get_tpex_existing_dates(codes: list[str]) -> dict[str, set[str]]:
    """取得各 TPEX 股票已有的日期集合"""
    conn = sqlite3.connect(DB_PATH)
    result = {}
    for code in codes:
        rows = conn.execute(
            'SELECT date FROM daily_prices WHERE stock_code=? AND date < 20250101',
            (code,)
        ).fetchall()
        result[code] = {r[0] for r in rows}
    conn.close()
    return result


def gen_bdays(start: str, end: str) -> list[str]:
    """產生所有工作日（週一至週五）的 YYYYMMDD 清單"""
    dates = pd.bdate_range(start=start, end=end)
    return [d.strftime('%Y%m%d') for d in dates]


def save_records(records: list[tuple]) -> int:
    if not records:
        return 0
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executemany(
        'INSERT OR IGNORE INTO daily_prices (stock_code, date, close_price) VALUES (?,?,?)',
        records
    )
    n = conn.total_changes
    conn.commit()
    conn.close()
    return n


def main():
    print('取得 TWSE 上市股清單...')
    twse_set = get_twse_stocks()
    print(f'  TWSE 上市: {len(twse_set)} 檔')
    time.sleep(0.5)

    twse_targets = [c for c in TARGET_STOCKS if c in twse_set]
    tpex_targets = [c for c in TARGET_STOCKS if c not in twse_set]
    print(f'  目標中 TWSE: {twse_targets}')
    print(f'  目標中 TPEX: {tpex_targets}')

    months = gen_months(START_MONTH, END_MONTH)
    print(f'\n月份: {months[0]} ~ {months[-1]}  共 {len(months)} 個月')
    print(f'目標: {len(TARGET_STOCKS)} 檔\n')

    total_new = 0

    # ── Phase A: TWSE 上市股（每檔每月）──
    print('─' * 50)
    print('Phase A: TWSE 上市股 (per stock per month)')
    for i, code in enumerate(twse_targets, 1):
        existing_months = get_existing_months(code)
        need_months = [m for m in months if m not in existing_months]
        print(f'  [{i:02d}/{len(twse_targets)}] {code} | 待抓 {len(need_months)} 月', end='', flush=True)
        stock_new = 0
        for ym in need_months:
            records = fetch_twse_month(code, ym)
            stock_new += save_records(records)
            time.sleep(0.35)
        total_new += stock_new
        print(f'  → +{stock_new} 筆')

    # ── Phase B: TPEX 上櫃股（批次抓取，每日一次）──
    print()
    print('─' * 50)
    print('Phase B: TPEX 上櫃股 (batch by date)')
    tpex_set = set(tpex_targets)
    existing_by_code = get_tpex_existing_dates(tpex_targets)
    bdays = gen_bdays(START_MONTH + '01', END_MONTH + '31')
    print(f'  上櫃目標: {tpex_targets}')
    print(f'  工作日數: {len(bdays)}')

    tpex_new = 0
    skipped = 0
    for i, date in enumerate(bdays, 1):
        # 如果所有目標股當天都已有資料，跳過
        all_have = all(date in existing_by_code.get(c, set()) for c in tpex_targets)
        if all_have:
            skipped += 1
            continue

        records = fetch_tpex_day(date, tpex_set)
        n = save_records(records)
        tpex_new += n
        # 更新快取
        for code, d, _ in records:
            existing_by_code.setdefault(code, set()).add(d)

        time.sleep(0.35)
        if i % 50 == 0:
            print(f'  進度: {i}/{len(bdays)} | 跳過: {skipped} | 新增: {tpex_new} 筆')

    print(f'  TPEX 完成: 跳過 {skipped} 日，新增 {tpex_new} 筆')
    total_new += tpex_new

    print(f'\n完成！總計新增 {total_new} 筆日收盤資料')

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT stock_code, COUNT(*), MIN(date), MAX(date) FROM daily_prices '
        'WHERE date < 20250101 AND stock_code IN ({}) '
        'GROUP BY stock_code ORDER BY stock_code'.format(
            ','.join('?' * len(TARGET_STOCKS))
        ),
        TARGET_STOCKS
    ).fetchall()
    conn.close()
    print()
    print('股票     | 日數 | 起    | 迄')
    for code, cnt, mn, mx in rows:
        print(f'{code:8s} | {cnt:4d} | {mn} | {mx}')


if __name__ == '__main__':
    main()
