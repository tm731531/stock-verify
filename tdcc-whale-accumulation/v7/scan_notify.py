"""
TDCC 掃描＋通知器 v2
=================
職責：
  - 每天確認資料是否最新，若舊了就先驅動抓取
  - 掃描雙引擎訊號並發 LINE 通知
  - 主引擎有訊號 → 發主引擎，補位不出現
  - 主引擎無訊號 → 補位引擎頂上（前5名）
  - 這週已通知過 → 直接結束（睡覺）

排程邏輯：
  週六 08:00   fetch_tdcc.py  → 主動抓資料（只抓）
  週日 21:00   scan_notify.py → 第一次嘗試通知
  週一 09:00   scan_notify.py → 第二次（週日沒抓到）
  週二~週四 09:00  scan_notify.py → 保底（極少用到）

用法:
  python3 scan_notify.py         # 正常執行
  python3 scan_notify.py --dry   # 不發 LINE，只印訊息
  python3 scan_notify.py --force # 忽略已通知記錄，強制重跑
"""

import json
import subprocess
import sys
import requests
import psycopg2
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE_DIR     = Path(__file__).parent
CONFIG_PATH  = BASE_DIR / 'scanner_config.json'
STATE_PATH   = BASE_DIR / 'scanner_state.json'
FETCH_SCRIPT = BASE_DIR / 'fetch_tdcc.py'

PG_CONFIG = dict(
    host='localhost', port=5432, dbname='tdcc',
    user='tdcc', password='tdcc1234',
)

# ── 主引擎參數 ──
MIN_STREAK     = 3
MIN_R400_CHG   = 3.0
MIN_SYNC       = 0.5
MAX_HOLDER_CHG = -2.0
MIN_PRICE      = 300.0
LIMIT_MULT     = 1.03

# ── 補位引擎參數 ──
FLEE_LOOKBACK_WEEKS = 3      # 回望幾週（改為3週）
FLEE_MIN_PCT        = -15.0  # 持有人至少跌幾%（改為15%）
BACKUP_R400_CHG     = 2.0    # 大戶增加幾%（新增條件）
MIN_PRICE_BACKUP    = 50.0   # 補位引擎最低股價
BACKUP_MA_PERIOD    = 20     # 需站上幾日均線
BACKUP_TOP_N        = 5      # LINE 通知最多顯示幾個補位訊號


# ── 設定 / 狀態 ───────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps({
            'LINE_CHANNEL_TOKEN': '',
            'LINE_USER_ID': '',
        }, ensure_ascii=False, indent=2))
        print(f'[scan] 請填入 {CONFIG_PATH} 的 LINE token')
        sys.exit(0)
    return json.loads(CONFIG_PATH.read_text())


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {'notified_signal_date': ''}


def save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2))


# ── 資料層 ────────────────────────────────────────────────────

class _PGConn:
    """讓 psycopg2 連線支援 conn.execute() 語法（與 sqlite3 相容）"""
    def __init__(self):
        self._conn = psycopg2.connect(**PG_CONFIG)
        self._cur  = self._conn.cursor()
    def execute(self, sql, params=None):
        self._cur.execute(sql, params)
        return self._cur
    def commit(self):   self._conn.commit()
    def close(self):    self._conn.close()
    def __iter__(self): return iter(self._cur)


def get_conn() -> _PGConn:
    return _PGConn()


def db_latest_date(conn) -> str:
    r = conn.execute('SELECT MAX(date) FROM holdings').fetchone()
    return r[0] or ''


def tdcc_latest_date() -> str:
    """探測最新 TDCC 日期（官方優先，Norway 後備）"""
    # 1. 官方 TDCC Open Data
    try:
        r = requests.get(
            'https://opendata.tdcc.com.tw/getOD.ashx?id=1-5',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=30,
            allow_redirects=True,
        )
        r.raise_for_status()
        r.encoding = 'utf-8-sig'
        for line in r.text.splitlines():
            parts = line.split(',')
            if len(parts) >= 2 and parts[0].strip().isdigit() and len(parts[0].strip()) == 8:
                print('[scan] 官方 TDCC 日期偵測成功')
                return parts[0].strip()
    except Exception as e:
        print(f'[scan] 官方 TDCC 偵測失敗: {e}')

    # 2. Norway 後備
    from bs4 import BeautifulSoup
    try:
        r = requests.get(
            'https://norway.twsthr.info/StockHolders.aspx?stock=3443',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=20,
        )
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if table:
            for row in table.find_all('tr')[1:]:
                cols = [c.get_text(strip=True) for c in row.find_all('td')]
                if len(cols) > 2:
                    d = cols[2].replace('/', '').replace('-', '')
                    if d.isdigit() and len(d) == 8:
                        print('[scan] Norway 後備日期偵測成功')
                        return d
    except Exception as e:
        print(f'[scan] Norway 偵測失敗: {e}')
    return ''


def try_fetch() -> bool:
    """驅動 fetch_tdcc.py，回傳是否成功取得新資料"""
    print('[scan] 驅動 fetch_tdcc.py...')
    result = subprocess.run(
        [sys.executable, str(FETCH_SCRIPT)],
        cwd=str(BASE_DIR.parent),
    )
    return result.returncode == 0


# ── 共用工具 ──────────────────────────────────────────────────

def iso_week_key(date_str: str) -> str:
    """'20260211' → '2026W07'，用來判斷同一週"""
    import datetime
    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'


def dedupe_by_week(grp: list) -> list:
    """
    同一 ISO 週只保留最後一筆（Norway 有時同週有兩筆，取最新的）
    grp 已按 date 升序
    """
    seen = {}
    for row in grp:
        wk = iso_week_key(row[1])
        seen[wk] = row
    return list(seen.values())


def load_stock_data(conn):
    """回傳 {code: [row,...]}，已按 date 升序"""
    rows = conn.execute(
        'SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders '
        'FROM holdings ORDER BY stock_code, date'
    ).fetchall()
    stock_data = defaultdict(list)
    for r in rows:
        stock_data[r[0]].append(r)
    return stock_data


def load_price_data(conn):
    """回傳 {code: {date: close_price}}"""
    prices = defaultdict(dict)
    for r in conn.execute('SELECT stock_code, date, close_price FROM daily_prices'):
        prices[r[0]][r[1]] = float(r[2])
    return prices


def build_special_stocks(stock_data: dict) -> set:
    """歷史上曾有單週 ratio_400_above 變動 >5% 的股票，永久排除（cummax）"""
    special = set()
    for code, grp in stock_data.items():
        r400 = [x[2] for x in grp]
        for k in range(1, len(r400)):
            if abs(r400[k] - r400[k - 1]) > 5.0:
                special.add(code)
                break
    return special


# ── 主引擎掃描 ────────────────────────────────────────────────

def scan_main_signals(conn) -> tuple[list[dict], str]:
    """
    掃描最新 TDCC 週的主引擎訊號。
    條件：連升≥3週 + 大戶↑≥3% + 同步≥50% + 散戶↓≥2% + 股價≥300
    回傳 (signals, tdcc_date)
    """
    tdcc_date = conn.execute('SELECT MAX(date) FROM holdings').fetchone()[0] or ''
    if not tdcc_date:
        return [], ''

    tdcc_week  = iso_week_key(tdcc_date)
    stock_data = load_stock_data(conn)
    prices     = load_price_data(conn)
    special    = build_special_stocks(stock_data)

    signals = []
    for code, grp in stock_data.items():
        if code in special:
            continue
        if code.startswith('00'):
            continue

        grp = dedupe_by_week(grp)
        if iso_week_key(grp[-1][1]) != tdcc_week:
            continue
        if len(grp) < 4:
            continue

        r400    = [x[2] for x in grp]
        r1000   = [x[3] for x in grp]
        holders = [x[4] for x in grp]
        i       = len(grp) - 1

        streak = 0
        for j in range(i, 0, -1):
            if r400[j] > r400[j - 1]: streak += 1
            else: break
        if streak < MIN_STREAK:
            continue

        si        = i - streak
        r400_chg  = r400[i] - r400[si]
        r1000_chg = r1000[i] - r1000[si]
        sync      = r1000_chg / r400_chg if r400_chg > 0.01 else 0
        h_chg     = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

        if r400_chg  < MIN_R400_CHG:  continue
        if sync      < MIN_SYNC:       continue
        if h_chg     > MAX_HOLDER_CHG: continue

        tdcc_day = grp[-1][1]
        price    = prices[code].get(tdcc_day, 0)
        if price < MIN_PRICE:
            continue

        limit_price = round(price * LIMIT_MULT, 1)
        signals.append({
            'signal_date': tdcc_date,
            'code':        code,
            'streak':      streak,
            'r400_chg':    round(r400_chg, 2),
            'r400_now':    round(r400[i], 2),
            'sync':        round(sync * 100, 1),
            'holder_chg':  round(h_chg, 1),
            'price':       price,
            'limit_price': limit_price,
            'stop_loss':   round(limit_price * 0.93, 1),
        })

    # 連升週數少的優先（新鮮訊號），同週數再看 r400_chg 大的
    return sorted(signals, key=lambda x: (x['streak'], -x['r400_chg'])), tdcc_date


# ── 補位引擎掃描 ──────────────────────────────────────────────

def scan_backup_signals(conn, tdcc_date: str) -> list[dict]:
    """
    補位引擎：散戶出逃 + 大戶進場 + 站上 MA20
    條件：3週持有人↓≥15% + 大戶↑≥2% + 股價站上MA20 + 股價≥50
    進場：TDCC日後第5個交易日（通知只給參考，不查未來價格）
    只掃最新 TDCC 週的訊號
    """
    if not tdcc_date:
        return []

    tdcc_week  = iso_week_key(tdcc_date)
    stock_data = load_stock_data(conn)

    # 每日收盤價（用於 MA20 計算）
    price_rows = conn.execute(
        'SELECT stock_code, date, close_price FROM daily_prices ORDER BY stock_code, date'
    ).fetchall()
    price_data = defaultdict(list)
    for r in price_rows:
        price_data[r[0]].append((r[1], float(r[2])))

    signals = []
    for code, grp in stock_data.items():
        if code.startswith('00'):
            continue

        grp = dedupe_by_week(grp)
        if len(grp) < FLEE_LOOKBACK_WEEKS + 1:
            continue
        if iso_week_key(grp[-1][1]) != tdcc_week:
            continue

        holders = [x[4] for x in grp]   # index 4 = total_holders
        r400    = [x[2] for x in grp]   # index 2 = ratio_400_above
        i       = len(grp) - 1
        h_now   = holders[i]
        h_bef   = holders[i - FLEE_LOOKBACK_WEEKS]
        if h_bef <= 0:
            continue
        flee = (h_now - h_bef) / h_bef * 100
        if flee > FLEE_MIN_PCT:
            continue

        # 大戶增加≥2%
        r400_now = float(r400[i] or 0)
        r400_bef = float(r400[i - FLEE_LOOKBACK_WEEKS] or 0)
        r400_chg = r400_now - r400_bef
        if r400_chg < BACKUP_R400_CHG:
            continue

        pdates = price_data.get(code, [])
        if not pdates:
            continue
        date_list  = [p[0] for p in pdates]
        close_list = [p[1] for p in pdates]

        tdcc_day = grp[-1][1]
        try:
            pi = next(k for k, d in enumerate(date_list) if d >= tdcc_day)
        except StopIteration:
            continue

        cp = close_list[pi]
        if cp < MIN_PRICE_BACKUP:
            continue

        # 站上 MA20（用 TDCC 日前20筆計算，不含當天）
        if pi < BACKUP_MA_PERIOD:
            continue
        ma20 = sum(close_list[pi - BACKUP_MA_PERIOD:pi]) / BACKUP_MA_PERIOD
        if cp < ma20:
            continue

        # ⚠️ scan_notify 不查未來價格，只用 TDCC 當天收盤做參考
        # 實際買入：TDCC 公布後第5個交易日，自行掛單
        signals.append({
            'signal_date': tdcc_date,
            'code':        code,
            'flee_pct':    round(flee, 1),
            'r400_chg':    round(r400_chg, 2),
            'holders_now': h_now,
            'tdcc_close':  round(cp, 1),
        })

    # 散戶跑幅最大的優先（負值愈小愈大幅出逃）
    return sorted(signals, key=lambda x: x['flee_pct'])


# ── LINE ──────────────────────────────────────────────────────

def send_line(token: str, user_id: str, msg: str, dry: bool) -> bool:
    if dry:
        print(f'\n[DRY] LINE 訊息:\n{msg}\n')
        return True
    if not token or not user_id:
        print('[LINE] 未設定 token')
        return False
    try:
        r = requests.post(
            'https://api.line.me/v2/bot/message/push',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={'to': user_id, 'messages': [{'type': 'text', 'text': msg}]},
            timeout=10,
        )
        ok = r.status_code == 200
        print(f'[LINE] {"✅ 成功" if ok else f"❌ {r.status_code} {r.text}"}')
        return ok
    except Exception as e:
        print(f'[LINE] 異常: {e}')
        return False


def build_message(main_signals: list[dict], backup_signals: list[dict],
                  db_date: str, signal_date: str) -> str:
    today  = date.today().strftime('%m/%d')
    db_str = f"{db_date[:4]}/{db_date[4:6]}/{db_date[6:]}"
    lines  = [f'\n🐋 TDCC 鯨魚掃描｜{today}', f'最新資料：{db_str}']

    sd = f"{signal_date[:4]}/{signal_date[4:6]}/{signal_date[6:]}" if signal_date else ''

    # ── 主引擎有訊號 → 只發主引擎，補位不出現 ──
    if main_signals:
        lines += ['', f'🎯 主引擎 {len(main_signals)} 個（TDCC {sd}）',
                  '訊號日後跳過2天，第3天起觀察收盤≤限價，隔天掛單（最多等5天）', '']
        for s in main_signals:
            lines += [
                f"【{s['code']}】連升{s['streak']}週｜大戶+{s['r400_chg']}%｜同步{s['sync']}%",
                f"  收盤 {s['price']:.0f} → 限價 ≤ {s['limit_price']:.1f} → 停損 ≤ {s['stop_loss']:.1f}",
                f"  大戶比例 {s['r400_now']}%｜散戶{s['holder_chg']:+.1f}%",
                '',
            ]
        lines.append('🛑 停損＝限價×0.93｜停利：+15%啟動，回落10%出場｜最長90天')
        return '\n'.join(lines)

    # ── 主引擎無訊號 → 補位引擎頂上 ──
    if backup_signals:
        top = backup_signals[:BACKUP_TOP_N]
        lines += ['', f'📌 補位引擎 前{len(top)}（3週散戶↓≥15% + 大戶↑≥2%，共{len(backup_signals)}個，TDCC {sd}）',
                  'TDCC日後第5個交易日收盤買入', '']
        for s in top:
            lines += [
                f"【{s['code']}】散戶跑{s['flee_pct']:+.1f}%｜大戶+{s['r400_chg']:.1f}%｜持有人{s['holders_now']:,}",
                f"  TDCC收盤 {s['tdcc_close']:.1f}｜TDCC後第5個交易日買入",
                '',
            ]
    else:
        lines += ['', '本週主引擎＋補位引擎均無訊號', '等下週 TDCC 更新']

    lines.append('🛑 停損＝限價×0.93｜停利：+15%啟動，回落10%出場｜最長90天')
    return '\n'.join(lines)


# ── 主流程 ────────────────────────────────────────────────────

def main():
    args  = sys.argv[1:]
    dry   = '--dry'   in args
    force = '--force' in args

    cfg     = load_config()
    state   = load_state()
    token   = cfg.get('LINE_CHANNEL_TOKEN', '')
    user_id = cfg.get('LINE_USER_ID', '')

    print(f'[scan] {date.today()} 啟動')

    # ── 1. 已通知過這週？→ 睡覺 ────────────────────────────
    conn    = get_conn()
    db_date = db_latest_date(conn)
    conn.close()

    if not force:
        conn = get_conn()
        _, current_signal_date = scan_main_signals(conn)
        conn.close()
        # 通知去重以主引擎 signal_date 為準
        if current_signal_date and state.get('notified_signal_date') == current_signal_date:
            print(f'[scan] 訊號日 {current_signal_date} 已通知過，睡覺 💤')
            return

    # ── 2. 資料是否最新？──────────────────────────────────
    print(f'[scan] DB 最新: {db_date}')
    tdcc_date = tdcc_latest_date()
    print(f'[scan] TDCC 最新: {tdcc_date}')

    if tdcc_date and tdcc_date > db_date:
        fetched = try_fetch()
        if not fetched:
            print('[scan] 抓取失敗，本次放棄，明天再試')
            send_line(token, user_id,
                f'⚠️ TDCC 抓取失敗\nDB: {db_date}｜TDCC: {tdcc_date}\n請手動檢查 fetch_tdcc.py',
                dry)
            return
        conn    = get_conn()
        db_date = db_latest_date(conn)
        conn.close()
        print(f'[scan] 更新後 DB 最新: {db_date}')

    elif not tdcc_date:
        print('[scan] ⚠️ 無法連到 TDCC，用現有資料繼續')

    # ── 3. 掃描雙引擎訊號 ───────────────────────────────
    conn = get_conn()
    main_signals, signal_date = scan_main_signals(conn)
    backup_signals = scan_backup_signals(conn, signal_date) if signal_date else []
    conn.close()
    print(f'[scan] 訊號日: {signal_date}｜主引擎: {len(main_signals)}｜補位: {len(backup_signals)}')

    # ── 4. 發 LINE ──────────────────────────────────────
    msg  = build_message(main_signals, backup_signals, db_date, signal_date)
    print(msg)
    sent = send_line(token, user_id, msg, dry)

    # ── 5. 記住已通知（以主引擎 signal_date 為準）──────
    if sent and not dry and signal_date:
        state['notified_signal_date'] = signal_date
        save_state(state)
        print(f'[scan] 記錄通知完成，訊號日 {signal_date}')

    print('[scan] 結束')


if __name__ == '__main__':
    main()
