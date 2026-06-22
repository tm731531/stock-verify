"""每日 0050 十日線/月線交叉狀態 → LINE 通知（只報狀態，不含買賣建議）。

- 訊號標的：0050（與回測一致，訊號與買賣都用 0050，非大盤指數）。
- 資料源：主 FinMind，掛了自動換備案 Yahoo；兩個都掛就 LINE 報錯。
- 取最近一根「已收盤」的交易日，算十日線(MA10)、月線(MA20)，判斷：
  往上交叉 / 往下交叉 / 岔開(多方在上) / 岔開(空方在下)。
- 自動還原分割（窗內若出現 1拆N 不會污染均線）。

用法：
  ./venv/bin/python daily_cross_notify.py          # 抓資料並送 LINE
  ./venv/bin/python daily_cross_notify.py --dry    # 只印不送（測試）
  ./venv/bin/python daily_cross_notify.py --yahoo  # 強制用備案 Yahoo（測試）
"""
import sys
import json
import urllib.request
from datetime import date, timedelta

from orbital_yang.notify import send_line

STOCK = "0050"
FAST, SLOW = 10, 20
UA = {"User-Agent": "Mozilla/5.0"}


def _finmind(days_back: int = 120):
    """主資料源：FinMind TaiwanStockPrice。"""
    end = date.today()
    start = end - timedelta(days=days_back)
    url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
           f"&data_id={STOCK}&start_date={start}&end_date={end}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        d = json.load(r)
    rows = sorted(d.get("data", []), key=lambda x: x["date"])
    return [(x["date"], float(x["close"])) for x in rows if x.get("close")]


def _yahoo():
    """備案資料源：Yahoo Finance 0050.TW（獨立 pipeline）。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{STOCK}.TW"
           "?range=4mo&interval=1d")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        d = json.load(r)
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    from datetime import datetime, timezone
    out = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        ds = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append((ds, float(c)))
    return sorted(out, key=lambda x: x[0])


def fetch_closes(force_yahoo: bool = False):
    """回傳 (closes, source_name)。主源失敗自動切備案；都失敗丟例外。"""
    sources = [("Yahoo", _yahoo)] if force_yahoo else [("FinMind", _finmind), ("Yahoo", _yahoo)]
    errs = []
    for name, fn in sources:
        try:
            rows = fn()
            if rows and len(rows) >= SLOW + 2:
                return rows, name
            errs.append(f"{name}: 資料筆數不足({len(rows)})")
        except Exception as e:
            errs.append(f"{name}: {e}")
    raise RuntimeError("；".join(errs))


def split_adjust(closes):
    """自動還原分割：單日漲跌 ratio<0.55 或 >1.8 視為分割，等比例還原分割前價格。"""
    vals = [c for _, c in closes]
    f = [1.0] * len(vals)
    for i in range(1, len(vals)):
        r = vals[i] / vals[i - 1]
        if r < 0.55 or r > 1.8:
            for j in range(i):
                f[j] *= r
    return [(closes[i][0], vals[i] * f[i]) for i in range(len(vals))]


def sma(vals, n, idx):
    return None if idx + 1 < n else sum(vals[idx - n + 1: idx + 1]) / n


def main():
    dry = "--dry" in sys.argv
    force_yahoo = "--yahoo" in sys.argv
    try:
        raw, source = fetch_closes(force_yahoo=force_yahoo)
        closes = split_adjust(raw)
    except Exception as e:
        send_line(f"⚠️ 0050 交叉腳本抓不到資料（主備源都失敗）：{e}", dry=dry)
        return

    dates = [d for d, _ in closes]
    vals = [c for _, c in closes]
    i = len(vals) - 1  # 最近一根已收盤交易日
    f_now, s_now = sma(vals, FAST, i), sma(vals, SLOW, i)
    f_prev, s_prev = sma(vals, FAST, i - 1), sma(vals, SLOW, i - 1)
    diff = f_now - s_now

    # 差距趨勢：收窄=正在靠近換邊（看5個交易日前）
    LOOKBACK = 5
    g_old = (sma(vals, FAST, i - LOOKBACK) - sma(vals, SLOW, i - LOOKBACK)
             if i - LOOKBACK >= SLOW else None)
    narrowing = g_old is not None and abs(diff) < abs(g_old)

    if f_prev <= s_prev and f_now > s_now:           # 今天剛上叉
        head, act, warn = "🟢 今天：買進", "👉 明天開盤 壓多 0050（全壓）", ""
    elif f_prev >= s_prev and f_now < s_now:         # 今天剛下叉
        head, act, warn = "🔴 今天：賣出", "👉 明天開盤 全部清掉、抱現金", ""
    elif f_now > s_now:                              # 多方持有中
        head, act = "🟩 今天：續抱", "👉 維持做多，不用動"
        warn = (f"⚠️ 快接近「賣出」了（差距 {g_old:+.1f}→{diff:+.1f} 收窄中），留意"
                if narrowing else "")
    else:                                            # 空手中
        head, act = "⬜ 今天：空手", "👉 維持現金、不要進場"
        warn = (f"⚠️ 快接近「買進」了（差距 {g_old:+.1f}→{diff:+.1f} 收窄中），留意"
                if narrowing else "")

    msg = (f"📈 0050 操作訊號｜{dates[i]}\n\n"
           f"{head}\n{act}\n"
           + (f"\n{warn}\n" if warn else "")
           + f"\n（參考：十日線{f_now:.1f}／月線{s_now:.1f}｜來源 {source}）")
    send_line(msg, dry=dry)


if __name__ == "__main__":
    main()
