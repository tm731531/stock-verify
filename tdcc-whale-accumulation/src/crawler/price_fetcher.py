"""Fetch Taiwan stock daily price data from TWSE/TPEX official APIs."""

import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

TWSE_DAY_ALL_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"
TPEX_QUOTES_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"
REQUEST_TIMEOUT = 15


def _to_roc_date(western_date: str) -> str:
    """Convert YYYYMMDD to ROC date format YYY/MM/DD."""
    y = int(western_date[:4]) - 1911
    return f"{y}/{western_date[4:6]}/{western_date[6:8]}"


class PriceFetcher:
    """Fetch daily close prices for all Taiwan stocks via batch APIs."""

    def __init__(self, request_delay: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.request_delay = request_delay
        # 快取: date -> {stock_code: close_price}
        self._cache: Dict[str, Dict[str, float]] = {}

    def fetch_market_day(self, date: str) -> Dict[str, float]:
        """
        Fetch close prices for ALL stocks on a given date.

        Args:
            date: Date in YYYYMMDD format.

        Returns:
            Dict mapping stock_code -> close_price.
        """
        if date in self._cache:
            return self._cache[date]

        prices = {}
        prices.update(self._fetch_twse_day(date))
        prices.update(self._fetch_tpex_day(date))
        self._cache[date] = prices
        return prices

    def _fetch_twse_day(self, date: str) -> Dict[str, float]:
        """Fetch all listed (上市) stocks' close prices for a date."""
        try:
            resp = self.session.get(
                TWSE_DAY_ALL_URL,
                params={"response": "json", "date": date},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("stat") != "OK" or "data" not in data:
                return {}

            prices = {}
            for row in data["data"]:
                code = row[0].strip()
                close_str = row[7].replace(",", "").strip()
                try:
                    prices[code] = float(close_str)
                except (ValueError, IndexError):
                    continue
            return prices

        except Exception as e:
            logger.warning(f"TWSE fetch failed for {date}: {e}")
            return {}

    def _fetch_tpex_day(self, date: str) -> Dict[str, float]:
        """Fetch all OTC (上櫃) stocks' close prices for a date."""
        try:
            roc_date = _to_roc_date(date)
            resp = self.session.get(
                TPEX_QUOTES_URL,
                params={"l": "zh-tw", "d": roc_date, "o": "json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            prices = {}
            for table in data.get("tables", []):
                for row in table.get("data", []):
                    code = row[0].strip()
                    close_str = row[2].replace(",", "").strip()
                    try:
                        prices[code] = float(close_str)
                    except (ValueError, IndexError):
                        continue
            return prices

        except Exception as e:
            logger.warning(f"TPEX fetch failed for {date}: {e}")
            return {}

    def fetch_stock_prices(
        self, stock_code: str, dates: List[str]
    ) -> pd.DataFrame:
        """
        Get close prices for a single stock across multiple dates.

        Args:
            stock_code: Stock code (e.g., '2330').
            dates: List of dates in YYYYMMDD format.

        Returns:
            DataFrame with DatetimeIndex and Close, change_pct columns.
        """
        rows = []
        for date in sorted(dates):
            market = self.fetch_market_day(date)
            if stock_code in market:
                rows.append({"date": date, "Close": market[stock_code]})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["date"], format="%Y%m%d")
        df.index.name = "Date"
        df = df.drop(columns=["date"])
        df["change_pct"] = df["Close"].pct_change() * 100
        return df

    def fetch_all_dates(self, dates: List[str]) -> None:
        """
        Pre-fetch and cache market data for multiple dates.
        Call this once before fetch_stock_prices to avoid repeated API calls.
        """
        for i, date in enumerate(dates):
            if date not in self._cache:
                logger.info(f"Fetching market prices for {date} ({i+1}/{len(dates)})...")
                self.fetch_market_day(date)
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

    def merge_with_tdcc(
        self, price_df: pd.DataFrame, tdcc_records: List[Dict]
    ) -> pd.DataFrame:
        """
        Merge price data with TDCC shareholding records by date.

        Args:
            price_df: DataFrame from fetch_stock_prices() with DatetimeIndex.
            tdcc_records: List of dicts with 'date' (YYYYMMDD) and ratio fields.

        Returns:
            price_df with TDCC columns joined (NaN for non-TDCC dates).
        """
        if not tdcc_records or price_df.empty:
            return price_df

        tdcc_df = pd.DataFrame(tdcc_records)
        tdcc_df["date"] = pd.to_datetime(tdcc_df["date"], format="%Y%m%d")
        tdcc_df = tdcc_df.set_index("date")

        merged = price_df.join(tdcc_df, how="left")
        return merged
