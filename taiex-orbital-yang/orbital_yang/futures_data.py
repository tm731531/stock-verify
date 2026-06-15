"""抓 FinMind 台指期 (TX) 日線, 取近月(成交量最大)+ 日盤, 做成連續日線 OHLC。"""
import json
import time
import urllib.request
import urllib.error
import pandas as pd

_BASE = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesDaily"
         "&data_id=TX&start_date={start}&end_date={end}")
_COLS = ["date", "open", "high", "low", "close", "volume"]


def select_daily_ohlc(rows: list) -> pd.DataFrame:
    """FinMind rows -> 每日近月(量最大)日盤 OHLC。

    欄位: date(datetime), open, high, low, close, volume。
    """
    df = pd.DataFrame(rows)
    for col in ["open", "max", "min", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    day = df[df["trading_session"] != "after_market"]
    use = day if len(day) else df
    use = use.dropna(subset=["close", "volume"])
    idx = use.groupby("date")["volume"].idxmax()      # 每日取量最大合約(近月)
    sel = use.loc[idx].rename(columns={"max": "high", "min": "low"}).copy()
    sel["date"] = pd.to_datetime(sel["date"])
    sel = sel.sort_values("date").reset_index(drop=True)
    return sel[_COLS]


def _fetch_chunk(start: str, end: str) -> list:
    url = _BASE.format(start=start, end=end)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        d = json.load(resp)
    if d.get("status") != 200:
        raise RuntimeError(f"FinMind status {d.get('status')}: {d.get('msg')}")
    return d.get("data", [])


def fetch_txf_daily(start: str, end: str, chunk_months: int = 6) -> pd.DataFrame:
    """分段抓 start~end 的 TX 日線並合併 (避免單次過大)。回傳連續日線 OHLC。"""
    bounds = pd.date_range(start=start, end=end, freq="MS").tolist()
    bounds = [pd.Timestamp(start)] + bounds + [pd.Timestamp(end)]
    bounds = sorted(set(bounds))
    all_rows = []
    i = 0
    while i < len(bounds) - 1:
        s = bounds[i]
        e_idx = min(i + chunk_months, len(bounds) - 1)
        e = bounds[e_idx]
        rows = _fetch_chunk(s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))
        all_rows.extend(rows)
        time.sleep(1.0)
        i = e_idx
    return select_daily_ohlc(all_rows)


def save_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False)
