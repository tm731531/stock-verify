"""
TDCC 資料抓取器
==============
職責：從 TDCC 官方 Open Data 抓取最新持股資料，存入本地 DB。
只負責資料，不算任何策略邏輯。

主要來源：TDCC 官方 Open Data（一次下載全部股票）
  URL: https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
  欄位：資料日期, 證券代號, 持股分級(1-17), 人數, 股數, 占集保庫存數比例%
  ratio_400_above  = tier 12+13+14+15 % 加總（≥400張）
  ratio_1000_above = tier 15 %（≥1000張）
  total_holders    = tier 17 人數

後備來源：Norway（official 失敗時自動切換，同時提供收盤價）

用法:
  python3 fetch_tdcc.py          # 自動偵測並更新新資料
  python3 fetch_tdcc.py --check  # 只查有沒有新資料，exit 0=有新 1=沒新
  python3 fetch_tdcc.py --force  # 強制重新抓最新一批

回傳 exit code:
  0 = 成功更新（有新資料）
  1 = 無新資料
  2 = 錯誤
"""

import csv
import io
import sys
import time
import requests
import psycopg2
from collections import defaultdict
from pathlib import Path

PG_CONFIG = dict(
    host='localhost', port=5432, dbname='tdcc',
    user='tdcc', password='tdcc1234',
)
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

# 官方 TDCC Open Data
TDCC_URL   = 'https://opendata.tdcc.com.tw/getOD.ashx?id=1-5'

# Norway 後備（用於持股 + 收盤價）
NORWAY_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={}'
IDX_DATE    = 2
IDX_HOLDERS = 4
IDX_R400    = 7
IDX_R1000   = 13
IDX_PRICE   = 14

# -----------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------

def get_conn():
    return psycopg2.connect(**PG_CONFIG)


def db_latest_date(conn) -> str:
    cur = conn.cursor()
    cur.execute('SELECT MAX(date) FROM holdings')
    r = cur.fetchone()
    return r[0] or ''


# -----------------------------------------------------------------
# 官方 TDCC Open Data
# -----------------------------------------------------------------

def tdcc_official_latest_date() -> str:
    """從官方 CSV 讀取最新 TDCC 日期（讀前幾行即可）"""
    try:
        r = requests.get(TDCC_URL, headers=HEADERS, timeout=30, allow_redirects=True)
        r.raise_for_status()
        r.encoding = 'utf-8-sig'
        for line in r.text.splitlines():
            parts = line.split(',')
            if len(parts) >= 2 and parts[0].strip().isdigit() and len(parts[0].strip()) == 8:
                return parts[0].strip()
    except Exception as e:
        print(f'[fetch] 官方日期偵測失敗: {e}', file=sys.stderr)
    return ''


def fetch_tdcc_official() -> tuple[str, dict]:
    """
    從官方下載全部股票最新週持股資料。
    回傳 (date_str, {stock_code: {ratio_400_above, ratio_1000_above, total_holders}})
    """
    print('[fetch] 下載官方 TDCC Open Data...', flush=True)
    r = requests.get(TDCC_URL, headers=HEADERS, timeout=120, allow_redirects=True)
    r.raise_for_status()
    r.encoding = 'utf-8-sig'

    date_found = ''
    by_code: dict[str, dict[int, dict]] = defaultdict(dict)

    reader = csv.reader(io.StringIO(r.text))
    for row in reader:
        if len(row) < 6:
            continue
        d = row[0].strip()
        if not d.isdigit() or len(d) != 8:
            continue  # skip header

        code = row[1].strip()
        if not code:
            continue
        try:
            tier = int(row[2].strip())
            pct  = float(row[5].strip())
            holders = row[3].strip()
        except (ValueError, IndexError):
            continue

        if not date_found:
            date_found = d

        by_code[code][tier] = {'holders': holders, 'pct': pct}

    if not date_found:
        return '', {}

    results: dict[str, dict] = {}
    for code, tiers in by_code.items():
        # ratio_400_above = tier 12~15 占比加總
        r400  = sum(tiers.get(t, {}).get('pct', 0.0) for t in [12, 13, 14, 15])
        # ratio_1000_above = tier 15 占比
        r1000 = tiers.get(15, {}).get('pct', 0.0)
        # total_holders = tier 17 人數
        try:
            total_h = int(tiers.get(17, {}).get('holders', '') or '0')
        except ValueError:
            total_h = 0

        results[code] = {
            'ratio_400_above':  round(r400, 2),
            'ratio_1000_above': round(r1000, 2),
            'total_holders':    total_h,
        }

    print(f'[fetch] 官方資料：{date_found}，共 {len(results)} 支股票', flush=True)
    return date_found, results


# -----------------------------------------------------------------
# Norway 後備
# -----------------------------------------------------------------

def norway_latest_date(sample_code='3443') -> str:
    """探測 Norway 最新日期（只爬一支代表股）"""
    try:
        r = requests.get(NORWAY_URL.format(sample_code), headers=HEADERS, timeout=20)
        r.raise_for_status()
        from bs4 import BeautifulSoup
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
        print(f'[fetch] Norway 日期偵測失敗: {e}', file=sys.stderr)
    return ''


def fetch_one_stock_norway(code: str) -> list[dict]:
    """爬取單一股票完整歷史（Norway，包含收盤價）"""
    try:
        from bs4 import BeautifulSoup
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
        print(f'  [{code}] Norway 爬取失敗: {e}', file=sys.stderr)
        return []


# -----------------------------------------------------------------
# 日期工具
# -----------------------------------------------------------------

def iso_week_key(date_str: str) -> str:
    import datetime
    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'


# -----------------------------------------------------------------
# 核心更新邏輯
# -----------------------------------------------------------------

def fetch_and_update_official(conn, new_date: str, holdings_data: dict) -> int:
    """
    用官方 TDCC bulk 資料更新 DB。
    holdings_data: {stock_code: {ratio_400_above, ratio_1000_above, total_holders}}
    回傳新增筆數。
    """
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT stock_code FROM holdings')
    all_codes = {r[0] for r in cur.fetchall()}

    # 只更新 DB 中已有的股票（避免引入不追蹤的股票）
    target_codes = all_codes & set(holdings_data.keys())
    print(f'[fetch] 官方更新 {len(target_codes)} 支股票（{new_date}）...', flush=True)

    cur = conn.cursor()
    total_new = 0
    for code in target_codes:
        data = holdings_data[code]
        if data['total_holders'] <= 0:
            continue  # 跳過無效資料
        cur.execute(
            'INSERT INTO holdings (stock_code, date, ratio_400_above, ratio_1000_above, total_holders) '
            'VALUES (%s, %s, %s, %s, %s) '
            'ON CONFLICT (stock_code, date) DO UPDATE SET '
            'ratio_400_above=EXCLUDED.ratio_400_above, '
            'ratio_1000_above=EXCLUDED.ratio_1000_above, '
            'total_holders=EXCLUDED.total_holders',
            (code, new_date,
             data['ratio_400_above'],
             data['ratio_1000_above'],
             data['total_holders'])
        )
        total_new += 1

    conn.commit()
    print(f'[fetch] ✅ 官方資料寫入完成，{total_new} 筆', flush=True)

    # 嘗試從 Norway 補收盤價（非必要，失敗不影響主流程）
    _update_prices_from_norway(conn, target_codes, new_date)

    return total_new


def _update_prices_from_norway(conn, codes: set, target_date: str) -> None:
    """向 Norway 補抓收盤價（batch），失敗不影響主流程"""
    print(f'[fetch] 補抓收盤價（Norway）...', flush=True)
    codes_list = list(codes)
    ok = 0
    fail = 0
    for i, code in enumerate(codes_list):
        try:
            records = fetch_one_stock_norway(code)
            cur = conn.cursor()
            for rec in records:
                if rec['date'] == target_date and rec['close_price'] > 0:
                    cur.execute(
                        'INSERT INTO daily_prices (stock_code, date, close_price) '
                        'VALUES (%s, %s, %s) '
                        'ON CONFLICT (stock_code, date) DO UPDATE SET close_price=EXCLUDED.close_price',
                        (code, rec['date'], rec['close_price'])
                    )
                    ok += 1
                    break
        except Exception:
            fail += 1
        time.sleep(0.2)
        if (i + 1) % 200 == 0:
            conn.commit()
            print(f'  [{i+1}/{len(codes_list)}] 價格補抓中...', flush=True)
    conn.commit()
    print(f'[fetch] 收盤價補抓完成（ok={ok} fail={fail}）', flush=True)


def fetch_and_update_norway(conn, since_date: str) -> int:
    """後備：全用 Norway 抓取（含持股 + 收盤價）"""
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT stock_code FROM holdings')
    all_codes = [r[0] for r in cur.fetchall()]

    total_new = 0
    print(f'[fetch] Norway 後備更新 {len(all_codes)} 支股票（since {since_date}）...')

    for i, code in enumerate(all_codes):
        records = fetch_one_stock_norway(code)
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

        nc = conn.cursor()
        for rec in new:
            nc.execute(
                'INSERT INTO holdings '
                '(stock_code, date, ratio_400_above, ratio_1000_above, total_holders) '
                'VALUES (%s, %s, %s, %s, %s) '
                'ON CONFLICT (stock_code, date) DO UPDATE SET '
                'ratio_400_above=EXCLUDED.ratio_400_above, '
                'ratio_1000_above=EXCLUDED.ratio_1000_above, '
                'total_holders=EXCLUDED.total_holders',
                (rec['stock_code'], rec['date'],
                 rec['ratio_400_above'], rec['ratio_1000_above'], rec['total_holders'])
            )
            if rec['close_price'] > 0:
                nc.execute(
                    'INSERT INTO daily_prices (stock_code, date, close_price) '
                    'VALUES (%s, %s, %s) '
                    'ON CONFLICT (stock_code, date) DO UPDATE SET close_price=EXCLUDED.close_price',
                    (rec['stock_code'], rec['date'], rec['close_price'])
                )
            total_new += 1

        time.sleep(0.3)
        if (i + 1) % 200 == 0:
            conn.commit()
            print(f'  [{i+1}/{len(all_codes)}] ...')

    conn.commit()
    return total_new


# -----------------------------------------------------------------
# 主程式
# -----------------------------------------------------------------

def main():
    args = sys.argv[1:]
    check_only = '--check' in args
    force      = '--force' in args

    conn     = get_conn()
    db_date  = db_latest_date(conn)

    # 1. 偵測最新日期（優先官方，失敗用 Norway）
    latest_date = tdcc_official_latest_date()
    source = 'official'
    if not latest_date:
        print('[fetch] 官方偵測失敗，改用 Norway...', file=sys.stderr)
        latest_date = norway_latest_date()
        source = 'norway'

    print(f'[fetch] DB 最新: {db_date} | TDCC 最新: {latest_date} ({source})')

    has_new = latest_date and (force or latest_date > db_date)

    if check_only:
        conn.close()
        if has_new:
            print(f'[fetch] ✅ 有新資料: {latest_date}')
            sys.exit(0)
        else:
            print('[fetch] ❌ 無新資料')
            sys.exit(1)

    if not has_new:
        print('[fetch] 無新資料，略過')
        conn.close()
        sys.exit(1)

    # 2. 抓取新資料
    total = 0
    if source == 'official' or force:
        try:
            new_date, holdings_data = fetch_tdcc_official()
            if new_date and holdings_data:
                total = fetch_and_update_official(conn, new_date, holdings_data)
                latest_date = new_date
            else:
                raise RuntimeError('官方資料為空')
        except Exception as e:
            print(f'[fetch] 官方抓取失敗: {e}，切換 Norway 後備...', file=sys.stderr)
            since = db_date if not force else ''
            total = fetch_and_update_norway(conn, since)
    else:
        # source == 'norway'，直接用 Norway
        since = db_date if not force else ''
        total = fetch_and_update_norway(conn, since)

    conn.close()

    if total > 0:
        print(f'[fetch] ✅ 完成，新增 {total} 筆，最新日期 {latest_date}')
        sys.exit(0)
    else:
        print('[fetch] ⚠️ 沒有寫入新資料')
        sys.exit(1)


if __name__ == '__main__':
    main()
