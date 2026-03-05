"""
TDCC 鯨魚積累策略 v7.2 — 每週自動掃描器
==========================================

執行時機：每週六、週日（cron 排程）
流程：
  1. 檢查 norway.twsthr.info 是否有新的 TDCC 資料
  2. 若有新資料 → 更新本地 DB（holdings + 收盤價）
  3. 掃描主引擎訊號（大戶連升 ≥3週 + 累計≥3% + ...）
  4. 有訊號 → LINE 通知（股票代碼 + 限價）
  5. 無訊號 → 也發 LINE（讓你知道腳本有跑）

設定：
  1. 複製 config.example.json 為 config.json
  2. 填入 LINE_TOKEN
  3. cron: 0 9 * * 6,7 /path/to/venv/bin/python3 /path/to/weekly_scanner.py

用法:
  python3 weekly_scanner.py           # 標準執行
  python3 weekly_scanner.py --force   # 強制重新掃描（不管有沒有新資料）
  python3 weekly_scanner.py --dry     # 試跑（不發 LINE）
"""

import json
import sqlite3
import time
import sys
import requests
import numpy as np
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, date

# ── 路徑設定 ─────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
DB_PATH    = BASE_DIR.parent / 'data' / 'tdcc_holdings.db'
CONFIG_PATH = BASE_DIR / 'scanner_config.json'
STATE_PATH  = BASE_DIR / 'scanner_state.json'   # 記住上次掃描的日期，避免重複通知

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
NORWAY_URL = 'https://norway.twsthr.info/StockHolders.aspx?stock={}'

# norway 頁面欄位索引（已驗證）
IDX_DATE    = 2
IDX_HOLDERS = 4
IDX_R400    = 7
IDX_R1000   = 13
IDX_PRICE   = 14


# ── 策略參數（v7.2）───────────────────────────────────────────────

MIN_STREAK      = 3
MIN_R400_CHG    = 3.0    # 累計增幅 ≥ 3%
MIN_SYNC        = 0.5    # 1000張同步性 ≥ 50%
MAX_HOLDER_CHG  = -2.0   # 散戶減少 ≥ 2%（負值）
MIN_PRICE       = 300.0  # 股價 ≥ 300
LIMIT_MULT      = 1.03   # 限價 = 訊號日收盤 × 1.03
ENTRY_DELAY     = 2      # 跳過 2 個交易日後開始觀察


# ── 設定檔 ────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        # 自動建立預設設定檔
        default = {
            "LINE_TOKEN": "請填入你的LINE_Notify_Token",
            "notify_even_if_no_signal": True,
        }
        CONFIG_PATH.write_text(json.dumps(default, ensure_ascii=False, indent=2))
        print(f"[設定] 已建立 {CONFIG_PATH}，請填入 LINE_TOKEN 後重新執行")
        sys.exit(0)
    return json.loads(CONFIG_PATH.read_text())


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"last_notified_tdcc_date": ""}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ── Step 1: 檢查是否有新資料 ──────────────────────────────────────

def get_latest_tdcc_date_in_db(conn) -> str:
    """DB 裡最新的 TDCC 日期"""
    r = conn.execute('SELECT MAX(date) FROM holdings').fetchone()
    return r[0] or ''


def probe_norway_latest_date(sample_code='3443') -> str:
    """
    爬一支代表性股票（3443）看 norway 最新有什麼日期
    回傳 'YYYYMMDD' 或 '' (失敗)
    """
    try:
        r = requests.get(NORWAY_URL.format(sample_code), headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if not table:
            return ''
        rows = table.find_all('tr')
        for row in rows[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cols) > IDX_DATE:
                d = cols[IDX_DATE].replace('/', '').replace('-', '')
                if d.isdigit() and len(d) == 8:
                    return d   # 第一行就是最新日期
        return ''
    except Exception as e:
        print(f'[探測] 失敗: {e}')
        return ''


# ── Step 2: 更新 DB ───────────────────────────────────────────────

def fetch_stock_norway(code: str) -> list[dict]:
    """爬取單一股票的完整 norway 數據"""
    try:
        r = requests.get(NORWAY_URL.format(code), headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if not table:
            return []
        rows = table.find_all('tr')
        records = []
        for row in rows[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cols) <= max(IDX_DATE, IDX_R400, IDX_R1000, IDX_HOLDERS, IDX_PRICE):
                continue
            d = cols[IDX_DATE].replace('/', '').replace('-', '')
            if not d.isdigit() or len(d) != 8:
                continue
            try:
                records.append({
                    'stock_code': code,
                    'date':       d,
                    'ratio_400_above':  float(cols[IDX_R400].replace(',', '')),
                    'ratio_1000_above': float(cols[IDX_R1000].replace(',', '')),
                    'total_holders':    int(cols[IDX_HOLDERS].replace(',', '')),
                    'close_price':      float(cols[IDX_PRICE].replace(',', '')),
                })
            except (ValueError, IndexError):
                continue
        return records
    except Exception as e:
        print(f'  [{code}] 爬取失敗: {e}')
        return []


def update_db(conn, new_tdcc_date: str, current_db_date: str) -> int:
    """
    更新 holdings 和 daily_prices
    只插入比 current_db_date 新的資料
    回傳新增筆數
    """
    # 取得所有股票清單
    all_codes = [r[0] for r in conn.execute(
        'SELECT DISTINCT stock_code FROM holdings'
    ).fetchall()]

    # 只需要更新最近 5 週的資料（策略需要 4 週歷史）
    # 實際上 norway 回傳全部，我們只插入新的
    total_new = 0
    print(f'[更新] 開始更新 {len(all_codes)} 支股票...')

    for i, code in enumerate(all_codes):
        records = fetch_stock_norway(code)
        new_records = [r for r in records if r['date'] > current_db_date]
        if not new_records:
            time.sleep(0.1)
            continue

        for rec in new_records:
            # holdings
            conn.execute(
                '''INSERT OR REPLACE INTO holdings
                   (stock_code, date, ratio_400_above, ratio_1000_above, total_holders)
                   VALUES (?, ?, ?, ?, ?)''',
                (rec['stock_code'], rec['date'],
                 rec['ratio_400_above'], rec['ratio_1000_above'], rec['total_holders'])
            )
            # daily_prices（用 norway 的收盤價）
            if rec['close_price'] > 0:
                conn.execute(
                    '''INSERT OR REPLACE INTO daily_prices (stock_code, date, close_price)
                       VALUES (?, ?, ?)''',
                    (rec['stock_code'], rec['date'], rec['close_price'])
                )
            total_new += 1

        time.sleep(0.3)

        if (i + 1) % 100 == 0:
            conn.commit()
            print(f'  [{i+1}/{len(all_codes)}] 已處理...')

    conn.commit()
    print(f'[更新] 完成，新增 {total_new} 筆')
    return total_new


# ── Step 3: 掃描主引擎訊號 ───────────────────────────────────────

def scan_signals(conn, tdcc_date: str) -> tuple[list[dict], str]:
    """
    掃描所有歷史資料，找最近一個有訊號的 TDCC 日期（同 strategy_v7.py 邏輯）
    只回報最新訊號日的訊號，避免通知已過時資料

    回傳: (signals_list, actual_signal_date)
    """
    from collections import defaultdict

    # 載入所有 holdings
    df_rows = conn.execute('''
        SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings
        ORDER BY stock_code, date
    ''').fetchall()

    stock_data = defaultdict(list)
    for row in df_rows:
        stock_data[row[0]].append(row)

    # 取得所有日期的收盤價
    all_prices = defaultdict(dict)
    for r in conn.execute('SELECT stock_code, date, close_price FROM daily_prices'):
        all_prices[r[0]][r[1]] = r[2]

    # 掃描每支股票的每個時間點（找所有歷史訊號）
    raw_signals = []  # (signal_date, code, streak, r400_chg, sync, h_chg, price)

    for code, rows in stock_data.items():
        if len(rows) < 4:
            continue

        r400    = [r[2] for r in rows]
        r1000   = [r[3] for r in rows]
        holders = [r[4] for r in rows]
        dates   = [r[1] for r in rows]

        for i in range(1, len(rows)):
            # 計算連升 streak
            streak = 0
            for j in range(i, 0, -1):
                if r400[j] > r400[j-1]:
                    streak += 1
                else:
                    break
            if streak < MIN_STREAK:
                continue

            si = i - streak
            r400_chg  = r400[i] - r400[si]
            r1000_chg = r1000[i] - r1000[si]
            sync      = r1000_chg / r400_chg if r400_chg > 0.01 else 0
            h_chg     = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

            if r400_chg < MIN_R400_CHG: continue
            if sync < MIN_SYNC:          continue
            if h_chg > MAX_HOLDER_CHG:   continue

            price = all_prices[code].get(dates[i], 0)
            if price < MIN_PRICE:
                continue

            raw_signals.append((dates[i], code, streak, r400_chg, r1000_chg, sync, h_chg, price, r400[i]))

    if not raw_signals:
        return [], tdcc_date

    # 找最近的訊號日（同 strategy_v7.py 的 scan_current）
    latest_signal_date = max(s[0] for s in raw_signals)
    current = [s for s in raw_signals if s[0] == latest_signal_date]

    signals = []
    for sig_date, code, streak, r400_chg, r1000_chg, sync, h_chg, price, r400_now in current:
        limit_price = round(price * LIMIT_MULT, 1)
        signals.append({
            'code':         code,
            'signal_date':  sig_date,
            'streak':       streak,
            'r400_chg':     round(r400_chg, 2),
            'r400_now':     round(r400_now, 2),
            'sync':         round(sync * 100, 1),
            'holder_chg':   round(h_chg, 1),
            'price':        price,
            'limit_price':  limit_price,
        })

    return sorted(signals, key=lambda x: -x['r400_chg']), latest_signal_date


# ── Step 4: LINE 通知 ─────────────────────────────────────────────

def send_line(channel_token: str, user_id: str, message: str, dry_run=False):
    if dry_run:
        print(f'\n[DRY RUN] LINE 訊息:\n{message}\n')
        return True
    if not channel_token or not user_id:
        print('[LINE] 未設定 channel_token 或 user_id，跳過通知')
        return False
    try:
        r = requests.post(
            'https://api.line.me/v2/bot/message/push',
            headers={
                'Authorization': f'Bearer {channel_token}',
                'Content-Type': 'application/json',
            },
            data=json.dumps({
                'to': user_id,
                'messages': [{'type': 'text', 'text': message}],
            }),
            timeout=10,
        )
        if r.status_code == 200:
            print('[LINE] 通知發送成功')
            return True
        else:
            print(f'[LINE] 發送失敗: {r.status_code} {r.text}')
            return False
    except Exception as e:
        print(f'[LINE] 發送異常: {e}')
        return False


def format_message(signals: list[dict], tdcc_date: str, signal_date: str,
                   has_new_data: bool) -> str:
    """組裝 LINE 訊息"""
    today = date.today().strftime('%m/%d')
    td = f"{tdcc_date[:4]}/{tdcc_date[4:6]}/{tdcc_date[6:]}"
    lines = [f'\n🐋 TDCC 鯨魚掃描 | {today} 更新']
    lines.append(f'DB 最新資料: {td}')

    if not has_new_data:
        lines.append('⚠️ Norway 尚未更新本週資料')
        lines.append('週一早上 9 點會再試一次')
        return '\n'.join(lines)

    if not signals:
        lines.append('本週無主引擎訊號')
        lines.append('等下週 TDCC 更新')
        return '\n'.join(lines)

    sd = f"{signal_date[:4]}/{signal_date[4:6]}/{signal_date[6:]}"
    lines.append(f'📢 發現 {len(signals)} 個訊號！（訊號日 {sd}）')
    lines.append(f'入場：訊號日後第3個交易日起，限價 ≤ 收盤 × 1.03')
    lines.append('')

    for s in signals:
        lines.append(
            f"【{s['code']}】"
            f" 連升{s['streak']}週 | "
            f"大戶+{s['r400_chg']}% | "
            f"同步{s['sync']}%"
        )
        lines.append(
            f"  訊號日收盤 {s['price']:.0f} → 限價 ≤ {s['limit_price']:.1f} 元"
        )
        lines.append(
            f"  大戶比例 {s['r400_now']}% | 散戶{s['holder_chg']:+.1f}%"
        )
        lines.append('')

    lines.append('⏰ 掛限價單，最多等 5 個交易日，買不到放棄')
    lines.append('🛑 停損 -7% | 停利追蹤（+15%啟動，回落10%觸發）')
    return '\n'.join(lines)


# ── 主程式 ────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    force   = '--force' in args
    dry_run = '--dry'   in args

    cfg           = load_config()
    state         = load_state()
    channel_token = cfg.get('LINE_CHANNEL_TOKEN', '')
    user_id       = cfg.get('LINE_USER_ID', '')
    notify_always = cfg.get('notify_even_if_no_signal', True)

    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M")}] TDCC 週掃描器啟動')

    conn = sqlite3.connect(DB_PATH)

    # Step 1: 檢查最新資料
    db_latest  = get_latest_tdcc_date_in_db(conn)
    nw_latest  = probe_norway_latest_date()
    print(f'[狀態] DB 最新: {db_latest} | Norway 最新: {nw_latest}')

    has_new_data = nw_latest and nw_latest > db_latest

    # Step 2: 如果有新資料就更新
    if has_new_data or force:
        if force and not has_new_data:
            print('[更新] --force 模式，強制使用 DB 現有資料掃描')
            nw_latest = db_latest
            has_new_data = True
        else:
            print(f'[更新] 新資料！開始更新到 {nw_latest}...')
            update_db(conn, nw_latest, db_latest)
    else:
        print('[狀態] 無新資料，跳過更新')
        if not notify_always:
            print('[結束] 無新資料且 notify_even_if_no_signal=false，結束')
            conn.close()
            return

    scan_date = nw_latest or db_latest

    # 避免重複通知同一個 TDCC 日期
    if not force and state.get('last_notified_tdcc_date') == scan_date and has_new_data:
        print(f'[狀態] {scan_date} 已通知過，略過（用 --force 強制重跑）')
        conn.close()
        return

    # Step 3: 掃描
    print(f'[掃描] 執行主引擎掃描...')
    if has_new_data:
        signals, signal_date = scan_signals(conn, scan_date)
    else:
        signals, signal_date = [], scan_date
    print(f'[掃描] 找到 {len(signals)} 個訊號，訊號日: {signal_date}')

    conn.close()

    # Step 4: LINE 通知
    msg = format_message(signals, scan_date, signal_date, has_new_data)
    print(msg)

    if has_new_data or notify_always:
        sent = send_line(channel_token, user_id, msg, dry_run)
        if sent and not dry_run and has_new_data:
            state['last_notified_tdcc_date'] = scan_date
            save_state(state)

    print('[完成]')


if __name__ == '__main__':
    main()
