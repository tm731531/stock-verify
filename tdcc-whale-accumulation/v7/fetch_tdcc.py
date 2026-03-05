"""
TDCC 資料抓取器
==============
職責：從 norway.twsthr.info 抓取最新 TDCC 持股資料，存入本地 DB。
只負責資料，不算任何策略邏輯。

用法:
  python3 fetch_tdcc.py          # 自動偵測並更新新資料
  python3 fetch_tdcc.py --check  # 只查有沒有新資料（不抓），exit 0=有新, 1=沒新
  python3 fetch_tdcc.py --force  # 強制重新抓最新一批（即使 DB 已有）

回傳 exit code:
  0 = 成功更新（有新資料）
  1 = 無新資料（Norway 尚未更新）
  2 = 錯誤
"""

import sqlite3
import sys
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

DB_PATH    = Path(__file__).parent.parent / 'data' / 'tdcc_holdings.db'
HEADERS    = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
NORWAY_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={}'

IDX_DATE    = 2
IDX_HOLDERS = 4
IDX_R400    = 7
IDX_R1000   = 13
IDX_PRICE   = 14


def db_latest_date(conn) -> str:
    r = conn.execute('SELECT MAX(date) FROM holdings').fetchone()
    return r[0] or ''


def norway_latest_date(sample_code='3443') -> str:
    """探測 Norway 最新日期（只爬一支代表股）"""
    try:
        r = requests.get(NORWAY_URL.format(sample_code), headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if not table:
            return ''
        for row in table.find_all('tr')[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cols) > IDX_DATE:
                d = cols[IDX_DATE].replace('/', '').replace('-', '')
                if d.isdigit() and len(d) == 8:
                    return d
    except Exception as e:
        print(f'[fetch] 探測失敗: {e}', file=sys.stderr)
    return ''


def fetch_one_stock(code: str) -> list[dict]:
    """爬取單一股票完整歷史"""
    try:
        r = requests.get(NORWAY_URL.format(code), headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if not table:
            return []
        records = []
        for row in table.find_all('tr')[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cols) <= max(IDX_DATE, IDX_R400, IDX_R1000, IDX_HOLDERS, IDX_PRICE):
                continue
            d = cols[IDX_DATE].replace('/', '').replace('-', '')
            if not d.isdigit() or len(d) != 8:
                continue
            try:
                records.append({
                    'stock_code':       code,
                    'date':             d,
                    'ratio_400_above':  float(cols[IDX_R400].replace(',', '')),
                    'ratio_1000_above': float(cols[IDX_R1000].replace(',', '')),
                    'total_holders':    int(cols[IDX_HOLDERS].replace(',', '')),
                    'close_price':      float(cols[IDX_PRICE].replace(',', '')),
                })
            except (ValueError, IndexError):
                continue
        return records
    except Exception as e:
        print(f'  [{code}] 爬取失敗: {e}', file=sys.stderr)
        return []


def iso_week_key(date_str: str) -> str:
    import datetime
    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'


def fetch_and_update(conn, since_date: str) -> int:
    """
    抓取所有股票在 since_date 之後的新資料，寫入 DB。
    同一 ISO 週只保留最新一筆（避免 Norway 修正重複問題）。
    回傳新增筆數。
    """
    all_codes = [r[0] for r in conn.execute(
        'SELECT DISTINCT stock_code FROM holdings'
    ).fetchall()]

    total_new = 0
    print(f'[fetch] 更新 {len(all_codes)} 支股票（since {since_date}）...')

    for i, code in enumerate(all_codes):
        records = fetch_one_stock(code)
        new = [r for r in records if r['date'] > since_date]
        if not new:
            time.sleep(0.1)
            continue

        # 同週只保留最新一筆
        week_latest: dict[str, dict] = {}
        for rec in new:
            wk = iso_week_key(rec['date'])
            if wk not in week_latest or rec['date'] > week_latest[wk]['date']:
                week_latest[wk] = rec
        new = list(week_latest.values())

        for rec in new:
            conn.execute(
                'INSERT OR REPLACE INTO holdings '
                '(stock_code, date, ratio_400_above, ratio_1000_above, total_holders) '
                'VALUES (?, ?, ?, ?, ?)',
                (rec['stock_code'], rec['date'],
                 rec['ratio_400_above'], rec['ratio_1000_above'], rec['total_holders'])
            )
            if rec['close_price'] > 0:
                conn.execute(
                    'INSERT OR REPLACE INTO daily_prices (stock_code, date, close_price) '
                    'VALUES (?, ?, ?)',
                    (rec['stock_code'], rec['date'], rec['close_price'])
                )
            total_new += 1

        time.sleep(0.3)
        if (i + 1) % 200 == 0:
            conn.commit()
            print(f'  [{i+1}/{len(all_codes)}] ...')

    conn.commit()
    return total_new


def main():
    args = sys.argv[1:]
    check_only = '--check' in args
    force      = '--force' in args

    conn = sqlite3.connect(DB_PATH)
    db_date  = db_latest_date(conn)
    nw_date  = norway_latest_date()

    print(f'[fetch] DB 最新: {db_date} | Norway 最新: {nw_date}')

    has_new = nw_date and nw_date > db_date

    if check_only:
        conn.close()
        if has_new:
            print(f'[fetch] ✅ 有新資料: {nw_date}')
            sys.exit(0)
        else:
            print('[fetch] ❌ 無新資料')
            sys.exit(1)

    if not has_new and not force:
        print('[fetch] 無新資料，略過')
        conn.close()
        sys.exit(1)

    since = db_date if not force else ''
    total = fetch_and_update(conn, since)
    conn.close()

    if total > 0:
        print(f'[fetch] ✅ 完成，新增 {total} 筆，最新日期 {nw_date}')
        sys.exit(0)
    else:
        print('[fetch] ⚠️ 沒有寫入新資料（可能股票清單未包含新股）')
        sys.exit(1)


if __name__ == '__main__':
    main()
