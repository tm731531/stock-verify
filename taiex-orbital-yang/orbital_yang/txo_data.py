"""抓 FinMind 真實 TXO 選擇權日線鏈 (含快取), 挑 ~30 權利金的真實選擇權。"""
import json
import time
import urllib.request
from pathlib import Path
import pandas as pd

CACHE = Path(__file__).parent.parent / "data" / "txo_cache"
_URL = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanOptionDaily"
        "&data_id=TXO&start_date={d}&end_date={d}")


def fetch_chain(date_str: str, use_cache: bool = True) -> pd.DataFrame:
    """抓某日 TXO 全鏈, 快取到 data/txo_cache/<date>.csv。回傳 DataFrame (失敗回空)。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    fp = CACHE / f"{date_str}.csv"
    if use_cache and fp.exists():
        return pd.read_csv(fp)
    req = urllib.request.Request(_URL.format(d=date_str), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        d = json.load(resp)
    if d.get("status") != 200:
        raise RuntimeError(f"FinMind {d.get('status')}: {d.get('msg')}")
    df = pd.DataFrame(d.get("data", []))
    df.to_csv(fp, index=False)
    time.sleep(1.0)
    return df


def _day_session(chain: pd.DataFrame) -> pd.DataFrame:
    if "trading_session" in chain.columns:
        day = chain[chain["trading_session"] != "after_market"]
        return day if len(day) else chain
    return chain


def pick_entry_option(chain: pd.DataFrame, kind: str, target_premium: float):
    """挑一口真實選擇權: 日盤、收盤>0、量>0 中, 收盤最接近 target_premium;

    同距離取成交量大者(較活躍/近月)。回傳 dict 或 None。
    """
    if chain is None or not len(chain):
        return None
    c = _day_session(chain)
    c = c[c["call_put"] == kind].copy()
    for col in ["close", "volume", "strike_price"]:
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c = c[(c["close"] > 0) & (c["volume"] > 0)].dropna(subset=["close", "strike_price"])
    if not len(c):
        return None
    c["dist"] = (c["close"] - target_premium).abs()
    c = c.sort_values(["dist", "volume"], ascending=[True, False])
    r = c.iloc[0]
    return {"contract_date": str(r["contract_date"]), "strike_price": float(r["strike_price"]),
            "call_put": kind, "close": float(r["close"])}


def lookup_premium(chain: pd.DataFrame, contract_date: str, strike_price: float, call_put: str):
    """在某日鏈找同一口合約的收盤; 找不到(已到期/未交易)回 None。"""
    if chain is None or not len(chain):
        return None
    c = _day_session(chain)
    c = c[(c["contract_date"].astype(str) == str(contract_date)) & (c["call_put"] == call_put)]
    c = c[pd.to_numeric(c["strike_price"], errors="coerce") == strike_price]
    if not len(c):
        return None
    v = pd.to_numeric(c["close"], errors="coerce").iloc[0]
    return None if pd.isna(v) else float(v)
