"""載入/刷新大盤日線 OHLC (yfinance ^TWII 格式)。"""
import pandas as pd

_COLS = ["open", "high", "low", "close", "volume"]


def load_daily(csv_path: str) -> pd.DataFrame:
    """讀 yfinance 匯出的日線 CSV,回傳乾淨 DataFrame。

    欄位: date, open, high, low, close, volume(date 為 datetime,已依日期排序)。
    """
    raw = pd.read_csv(csv_path)
    first = raw.columns[0]
    # yfinance 匯出開頭有 'Ticker' / 'Date' 雜訊列(2-row 或 3-row 格式),丟掉
    raw = raw[~raw[first].astype(str).isin(["Ticker", "Date"])].copy()
    raw = raw.rename(columns={first: "date"})
    raw.columns = [str(c).lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["date"])
    for c in _COLS:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = (
        raw.dropna(subset=["open", "close"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    return raw[["date"] + _COLS]


def refresh_daily(csv_path: str, ticker: str = "^TWII", period: str = "5y") -> pd.DataFrame:
    """用 yfinance 抓最新日線寫入 csv_path,並回傳 load_daily 結果。"""
    import yfinance as yf

    df = yf.download(ticker, period=period, auto_adjust=False, progress=False)
    df = df.reset_index()
    df.to_csv(csv_path, index=False)
    return load_daily(csv_path)
