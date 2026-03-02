"""Fetch Taiwan stock daily price data via yfinance."""

import logging
from typing import Dict, List

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class PriceFetcher:
    """Fetch daily OHLCV data for Taiwan stocks."""

    def fetch(self, stock_code: str, start: str, end: str) -> pd.DataFrame:
        """
        Fetch daily price data for a stock.

        Args:
            stock_code: Taiwan stock code (e.g., '2330')
            start: Start date 'YYYY-MM-DD'
            end: End date 'YYYY-MM-DD'

        Returns:
            DataFrame with Open, High, Low, Close, Volume, change_pct columns.
        """
        ticker = f"{stock_code}.TW"
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty:
                logger.warning(f"No price data for {ticker}")
                return pd.DataFrame()

            # yfinance 可能回傳 MultiIndex columns，展平
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 計算日漲跌幅 (%)
            df["change_pct"] = df["Close"].pct_change() * 100

            return df

        except Exception as e:
            logger.error(f"Error fetching price for {ticker}: {e}")
            return pd.DataFrame()

    def merge_with_tdcc(
        self, price_df: pd.DataFrame, tdcc_records: List[Dict]
    ) -> pd.DataFrame:
        """
        Merge price data with TDCC shareholding records by date.

        Args:
            price_df: DataFrame from fetch() with DatetimeIndex
            tdcc_records: List of dicts with 'date' (YYYYMMDD) and ratio fields

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
