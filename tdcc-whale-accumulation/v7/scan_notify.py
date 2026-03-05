"""
TDCC 掃描＋通知器
=================
職責：
  - 每天確認資料是否最新，若舊了就先驅動抓取
  - 掃描訊號並發 LINE 通知
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
import sqlite3
import subprocess
import sys
import requests
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE_DIR     = Path(__file__).parent
DB_PATH      = BASE_DIR.parent / 'data' / 'tdcc_holdings.db'
CONFIG_PATH  = BASE_DIR / 'scanner_config.json'
STATE_PATH   = BASE_DIR / 'scanner_state.json'
FETCH_SCRIPT = BASE_DIR / 'fetch_tdcc.py'

MIN_STREAK     = 3
MIN_R400_CHG   = 3.0
MIN_SYNC       = 0.5
MAX_HOLDER_CHG = -2.0
MIN_PRICE      = 300.0
LIMIT_MULT     = 1.03


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

def db_latest_date(conn) -> str:
    r = conn.execute('SELECT MAX(date) FROM holdings').fetchone()
    return r[0] or ''


def norway_latest_date(sample='3443') -> str:
    """探測 Norway 最新日期"""
    from bs4 import BeautifulSoup
    try:
        r = requests.get(
            f'https://norway.twsthr.info/StockHolders.aspx?stock={sample}',
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=20,
        )
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'Details'})
        if not table:
            return ''
        for row in table.find_all('tr')[1:]:
            cols = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cols) > 2:
                d = cols[2].replace('/', '').replace('-', '')
                if d.isdigit() and len(d) == 8:
                    return d
    except Exception as e:
        print(f'[scan] 探測 Norway 失敗: {e}')
    return ''


def try_fetch() -> bool:
    """驅動 fetch_tdcc.py，回傳是否成功取得新資料"""
    print('[scan] 驅動 fetch_tdcc.py...')
    result = subprocess.run(
        [sys.executable, str(FETCH_SCRIPT)],
        cwd=str(BASE_DIR.parent),
    )
    return result.returncode == 0


# ── 訊號掃描 ──────────────────────────────────────────────────

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
        seen[wk] = row   # 同週後面的覆蓋前面的
    return list(seen.values())  # dict 保持插入順序 (Python 3.7+)


def current_price(conn, code: str) -> float:
    """取該股票最新一日的收盤價（今天或最近交易日）"""
    r = conn.execute(
        'SELECT close_price FROM daily_prices WHERE stock_code=? ORDER BY date DESC LIMIT 1',
        (code,)
    ).fetchone()
    return float(r[0]) if r else 0.0


def scan_signals(conn) -> tuple[list[dict], str]:
    """
    掃描最新 TDCC 週的主引擎訊號。
    - 同週重複資料自動去重（取最後一筆）
    - 收盤價取最新交易日現價
    回傳 (signals, tdcc_date)
    """
    tdcc_date = conn.execute('SELECT MAX(date) FROM holdings').fetchone()[0] or ''
    if not tdcc_date:
        return [], ''

    tdcc_week = iso_week_key(tdcc_date)

    rows = conn.execute(
        'SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders '
        'FROM holdings ORDER BY stock_code, date'
    ).fetchall()

    stock_data = defaultdict(list)
    for r in rows:
        stock_data[r[0]].append(r)

    prices = defaultdict(dict)
    for r in conn.execute('SELECT stock_code, date, close_price FROM daily_prices'):
        prices[r[0]][r[1]] = r[2]

    # 特殊事件標記：歷史上曾有單週 >5% 的股票永久排除（與回測一致）
    special_stocks = set()
    for code, grp in stock_data.items():
        r400_all = [x[2] for x in grp]
        for k in range(1, len(r400_all)):
            if abs(r400_all[k] - r400_all[k-1]) > 5.0:
                special_stocks.add(code)
                break

    signals = []
    for code, grp in stock_data.items():
        if code in special_stocks:
            continue

        # 去重：同 ISO 週只保留最後一筆
        grp = dedupe_by_week(grp)

        # 最後一筆必須是最新 TDCC 週
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
            if r400[j] > r400[j-1]: streak += 1
            else: break
        if streak < MIN_STREAK: continue

        si        = i - streak
        r400_chg  = r400[i] - r400[si]
        r1000_chg = r1000[i] - r1000[si]
        sync      = r1000_chg / r400_chg if r400_chg > 0.01 else 0
        h_chg     = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

        if r400_chg  < MIN_R400_CHG:  continue
        if sync      < MIN_SYNC:       continue
        if h_chg     > MAX_HOLDER_CHG: continue

        # 用 TDCC 日當天收盤（限價計算的 anchor）
        tdcc_day = grp[-1][1]   # 去重後最後一筆的實際日期
        price = prices[code].get(tdcc_day, 0)
        if price < MIN_PRICE: continue

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

    # 排序：連升週數少的優先（新鮮訊號），同週數再看 r400_chg 大的
    return sorted(signals, key=lambda x: (x['streak'], -x['r400_chg'])), tdcc_date


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


def build_message(signals: list[dict], db_date: str, signal_date: str) -> str:
    today  = date.today().strftime('%m/%d')
    db_str = f"{db_date[:4]}/{db_date[4:6]}/{db_date[6:]}"
    lines  = [f'\n🐋 TDCC 鯨魚掃描｜{today}', f'最新資料：{db_str}']

    if not signals:
        lines += ['', '本週無主引擎訊號', '等下週 TDCC 更新']
        return '\n'.join(lines)

    sd = f"{signal_date[:4]}/{signal_date[4:6]}/{signal_date[6:]}"
    lines += ['', f'📢 {len(signals)} 個訊號（TDCC {sd}）',
              '訊號日後跳過2天，第3天起掛限價單（最多等5天）', '']

    for s in signals:
        lines += [
            f"【{s['code']}】連升{s['streak']}週｜大戶+{s['r400_chg']}%｜同步{s['sync']}%",
            f"  收盤 {s['price']:.0f} → 限價 ≤ {s['limit_price']:.1f} → 停損 ≤ {s['stop_loss']:.1f}",
            f"  大戶比例 {s['r400_now']}%｜散戶{s['holder_chg']:+.1f}%",
            '',
        ]

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
    conn        = sqlite3.connect(DB_PATH)
    db_date     = db_latest_date(conn)
    conn.close()

    if not force:
        # 掃一次看目前的 signal_date 是什麼
        conn = sqlite3.connect(DB_PATH)
        _, current_signal_date = scan_signals(conn)
        conn.close()

        if current_signal_date and state.get('notified_signal_date') == current_signal_date:
            print(f'[scan] 訊號日 {current_signal_date} 已通知過，睡覺 💤')
            return

    # ── 2. 資料是否最新？──────────────────────────────────
    print(f'[scan] DB 最新: {db_date}')
    nw_date = norway_latest_date()
    print(f'[scan] Norway 最新: {nw_date}')

    if nw_date and nw_date > db_date:
        # 有新資料 → 先抓
        fetched = try_fetch()
        if not fetched:
            print('[scan] 抓取失敗，本次放棄，明天再試')
            return
        # 更新 db_date
        conn    = sqlite3.connect(DB_PATH)
        db_date = db_latest_date(conn)
        conn.close()
        print(f'[scan] 更新後 DB 最新: {db_date}')

    elif not nw_date:
        print('[scan] ⚠️ 無法連到 Norway，用現有資料繼續')

    # ── 3. 掃描訊號 ─────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    signals, signal_date = scan_signals(conn)
    conn.close()
    print(f'[scan] 訊號日: {signal_date}｜訊號數: {len(signals)}')

    # ── 4. 發 LINE ──────────────────────────────────────
    msg  = build_message(signals, db_date, signal_date)
    print(msg)
    sent = send_line(token, user_id, msg, dry)

    # ── 5. 記住已通知 ────────────────────────────────────
    if sent and not dry and signal_date:
        state['notified_signal_date'] = signal_date
        save_state(state)
        print(f'[scan] 記錄通知完成，訊號日 {signal_date}')

    print('[scan] 結束')


if __name__ == '__main__':
    main()
