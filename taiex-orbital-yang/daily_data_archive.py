"""每日資料歸檔（給未來分析用，不發 LINE，純存本機）。

1. 0050 日線 OHLCV → 持續 append 到 data/0050_daily_log.csv（一交易日一行，去重）
2. 0050 前一天 5分K → data/intraday/0050_YYYY-MM-DD.csv（每交易日一檔）

資料源：日線 FinMind（免token）、分K Yahoo（interval=5m）。只存「已收完」的日子，跳過今天。
首次執行會一次補上近一個月的分K。

用法：
  ./venv/bin/python daily_data_archive.py
"""
import csv
import json
import urllib.request
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

HERE = Path(__file__).parent
STOCK = "0050"
UA = {"User-Agent": "Mozilla/5.0"}
TW = timezone(timedelta(hours=8))
LOG = HERE / "data" / f"{STOCK}_daily_log.csv"
INTRADAY_DIR = HERE / "data" / "intraday"


def append_daily_log():
    """把 FinMind 日線中、log 還沒有的交易日 append 上去（去重、自動補漏）。"""
    start = (date.today() - timedelta(days=30)).isoformat()
    url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
           f"&data_id={STOCK}&start_date={start}&end_date={date.today().isoformat()}")
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
    rows = sorted(d.get("data", []), key=lambda x: x["date"])
    existing = set()
    if LOG.exists():
        existing = {ln.split(",")[0] for ln in LOG.read_text().splitlines()[1:]}
    new = [r for r in rows if r["date"] not in existing and r.get("close")]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    write_header = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["date", "open", "high", "low", "close", "volume"])
        for r in new:
            w.writerow([r["date"], r["open"], r["max"], r["min"], r["close"],
                        r.get("Trading_Volume", "")])
    return len(new), new[-1]["date"] if new else None


def archive_intraday():
    """抓 Yahoo 5分K，把每個『已收完』交易日各存一檔（已存的跳過）。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{STOCK}.TW"
           "?interval=5m&range=1mo")
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
    r = d["chart"]["result"][0]
    ts, q = r["timestamp"], r["indicators"]["quote"][0]
    today = date.today().isoformat()
    bydate = {}
    for i, t in enumerate(ts):
        dtt = datetime.fromtimestamp(t, TW)
        ds = dtt.strftime("%Y-%m-%d")
        if ds >= today:                      # 跳過今天（未收完）
            continue
        o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i],
                         q["close"][i], q["volume"][i])
        if None in (o, h, l, c):
            continue
        bydate.setdefault(ds, []).append(
            [dtt.strftime("%H:%M"), round(o, 2), round(h, 2),
             round(l, 2), round(c, 2), int(v or 0)])
    INTRADAY_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for ds, bars in sorted(bydate.items()):
        fp = INTRADAY_DIR / f"{STOCK}_{ds}.csv"
        if fp.exists():
            continue
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            w.writerows(bars)
        saved.append(ds)
    return saved


def main():
    try:
        n, last = append_daily_log()
        print(f"[日線] append {n} 筆（最新 {last}）→ {LOG.name}")
    except Exception as e:
        print(f"[日線] 失敗：{e}")
    try:
        saved = archive_intraday()
        print(f"[分K] 新存 {len(saved)} 天 {saved} → data/intraday/")
    except Exception as e:
        print(f"[分K] 失敗：{e}")


if __name__ == "__main__":
    main()
