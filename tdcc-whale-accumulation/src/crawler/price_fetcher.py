"""Fetch Taiwan stock daily price data from TWSE/TPEX official APIs with SQLite persistence."""

import logging
import os
import sqlite3
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# TWSE 上市: 全市場某日收盤行情 (大量請求時常 timeout)
TWSE_MI_INDEX_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
# TWSE 上市: 個股月成交資訊 (穩定，一次回傳一檔一個月)
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
# TWSE 上市: 全市場當日 (只回傳最新日，用來取上市股清單)
TWSE_STOCK_DAY_ALL_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"
# TPEX 上櫃: 全市場某日收盤行情
TPEX_HIST_URL = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"

REQUEST_TIMEOUT = 20

CREATE_PRICES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_prices (
    stock_code TEXT NOT NULL,
    date TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL NOT NULL,
    volume INTEGER,
    PRIMARY KEY (stock_code, date)
)
"""


def _to_roc_date(western_date: str) -> str:
    """Convert YYYYMMDD to ROC date format YYY/MM/DD."""
    y = int(western_date[:4]) - 1911
    return f"{y}/{western_date[4:6]}/{western_date[6:8]}"


def _roc_to_western(roc_date: str) -> str:
    """Convert ROC date YYY/MM/DD to YYYYMMDD."""
    parts = roc_date.strip().split("/")
    y = int(parts[0]) + 1911
    return f"{y}{parts[1]}{parts[2]}"


class PriceFetcher:
    """Fetch daily close prices for all Taiwan stocks via batch APIs with SQLite cache."""

    def __init__(self, request_delay: float = 0.5, db_path: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        self.request_delay = request_delay
        self.db_path = db_path
        # 快取: date -> {stock_code: close_price}
        self._cache: Dict[str, Dict[str, float]] = {}

        if self.db_path:
            self._init_db()

    # ── DB 操作 ─────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(CREATE_PRICES_TABLE_SQL)
        conn.commit()
        conn.close()

    def _load_from_db(self, date: str) -> Optional[Dict[str, float]]:
        """Load prices for a date from SQLite. Returns None if no data."""
        if not self.db_path:
            return None
        conn = sqlite3.connect(self.db_path, timeout=30)
        rows = conn.execute(
            "SELECT stock_code, close_price FROM daily_prices WHERE date = ?",
            (date,),
        ).fetchall()
        conn.close()
        if not rows:
            return None
        return {r[0]: r[1] for r in rows}

    def _save_to_db(self, date: str, prices: Dict[str, float]):
        """Save prices for a date to SQLite."""
        if not self.db_path or not prices:
            return
        conn = sqlite3.connect(self.db_path, timeout=30)
        for code, price in prices.items():
            conn.execute(
                "INSERT OR IGNORE INTO daily_prices (stock_code, date, close_price) VALUES (?, ?, ?)",
                (code, date, price),
            )
        conn.commit()
        conn.close()

    def _save_batch_to_db(self, records: List[tuple]):
        """Save a batch of (stock_code, date, open_price, high_price, low_price, close_price, volume) to SQLite.
        Uses INSERT OR REPLACE to update existing records with new OHLCV data."""
        if not self.db_path or not records:
            return
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.executemany(
            "INSERT OR REPLACE INTO daily_prices (stock_code, date, open_price, high_price, low_price, close_price, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        conn.commit()
        conn.close()

    def _get_db_dates_for_stock(self, stock_code: str) -> set:
        """Get all dates already in DB for a stock."""
        if not self.db_path:
            return set()
        conn = sqlite3.connect(self.db_path, timeout=30)
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_prices WHERE stock_code = ?",
            (stock_code,),
        ).fetchall()
        conn.close()
        return set(r[0] for r in rows)

    def _get_db_stock_count_for_date(self, date: str) -> int:
        """Get number of stocks in DB for a date."""
        if not self.db_path:
            return 0
        conn = sqlite3.connect(self.db_path, timeout=30)
        n = conn.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE date = ?", (date,)
        ).fetchone()[0]
        conn.close()
        return n

    # ── 主要抓取方法 ───────────────────────────────────────

    def fetch_market_day(self, date: str) -> Dict[str, float]:
        """
        Fetch close prices for ALL stocks on a given date.
        Checks memory cache -> SQLite -> API (and saves back).
        Uses TPEX batch API. For TWSE, use fetch_twse_stock_month().
        """
        if date in self._cache:
            return self._cache[date]

        # Try SQLite
        db_prices = self._load_from_db(date)
        if db_prices:
            self._cache[date] = db_prices
            return db_prices

        # Fetch from API (TPEX only - TWSE uses STOCK_DAY separately)
        prices = {}
        prices.update(self._fetch_tpex_day(date))
        self._cache[date] = prices

        # Persist to SQLite
        self._save_to_db(date, prices)

        return prices

    def fetch_twse_stock_month(self, stock_code: str, year_month: str) -> List[tuple]:
        """
        Fetch one TWSE stock's daily data for an entire month via STOCK_DAY.

        Args:
            stock_code: e.g. '2330'
            year_month: YYYYMM format, e.g. '202503'

        Returns:
            List of (stock_code, date_YYYYMMDD, open_price, high_price, low_price, close_price, volume) tuples.
        """
        date_param = f"{year_month}01"
        try:
            resp = self.session.get(
                TWSE_STOCK_DAY_URL,
                params={"response": "json", "date": date_param, "stockNo": stock_code},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("stat") != "OK":
                return []

            # fields: 日期(ROC), 成交股數(idx 1), 成交金額(idx 2), 開盤價(idx 3), 最高價(idx 4), 最低價(idx 5), 收盤價(idx 6), 漲跌價差, 成交筆數
            records = []
            for row in data.get("data", []):
                try:
                    western_date = _roc_to_western(row[0])
                    open_str = row[3].replace(",", "").strip()
                    high_str = row[4].replace(",", "").strip()
                    low_str = row[5].replace(",", "").strip()
                    close_str = row[6].replace(",", "").strip()
                    volume_str = row[1].replace(",", "").strip()

                    open_price = float(open_str) if open_str else None
                    high_price = float(high_str) if high_str else None
                    low_price = float(low_str) if low_str else None
                    close_price = float(close_str) if close_str else None
                    volume = int(volume_str) if volume_str and volume_str.isdigit() else None

                    records.append((stock_code, western_date, open_price, high_price, low_price, close_price, volume))
                except (ValueError, IndexError):
                    continue

            return records

        except Exception as e:
            logger.warning(f"STOCK_DAY failed for {stock_code} {year_month}: {e}")
            return []

    def get_twse_listed_stocks(self) -> List[str]:
        """Get all TWSE listed stock codes via STOCK_DAY_ALL (latest day snapshot)."""
        try:
            resp = self.session.get(
                TWSE_STOCK_DAY_ALL_URL,
                params={"response": "json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            codes = []
            for row in data.get("data", []):
                code = row[0].strip()
                codes.append(code)
            logger.info(f"TWSE 上市股清單: {len(codes)} 檔")
            return codes
        except Exception as e:
            logger.warning(f"STOCK_DAY_ALL failed: {e}")
            return []

    def sync_twse_stocks(self, stock_codes: List[str], start_month: str, end_month: str, force: bool = False):
        """
        Bulk sync TWSE stocks via STOCK_DAY (per-stock per-month).
        Incremental: skips months already fully in DB (unless force=True).

        Args:
            stock_codes: List of TWSE stock codes to fetch.
            start_month: Start month YYYYMM (e.g. '202503').
            end_month: End month YYYYMM (e.g. '202602').
            force: If True, re-fetch all months even if data exists.
        """
        # Generate month list
        months = []
        current = pd.Timestamp(start_month + "01")
        end = pd.Timestamp(end_month + "01")
        while current <= end:
            months.append(current.strftime("%Y%m"))
            current += pd.offsets.MonthBegin(1)

        total_tasks = len(stock_codes) * len(months)
        done = 0
        skipped = 0
        new_records = 0

        logger.info(
            f"TWSE 同步: {len(stock_codes)} 檔 × {len(months)} 月 = {total_tasks} 任務"
        )

        for i, code in enumerate(stock_codes):
            existing_dates = self._get_db_dates_for_stock(code)

            for month in months:
                done += 1

                # Check if we already have data for this month
                # A month is "complete" if we have >= 15 trading days for it
                if not force:
                    month_dates = [d for d in existing_dates if d[:6] == month]
                    if len(month_dates) >= 15:
                        skipped += 1
                        continue

                records = self.fetch_twse_stock_month(code, month)
                if records:
                    self._save_batch_to_db(records)
                    new_records += len(records)
                    # Update existing_dates for subsequent month checks
                    existing_dates.update(r[1] for r in records)

                if self.request_delay > 0:
                    time.sleep(self.request_delay)

                if done % 100 == 0:
                    logger.info(
                        f"  進度: {done}/{total_tasks} ({done/total_tasks*100:.1f}%) "
                        f"| 跳過: {skipped} | 新增: {new_records} 筆 "
                        f"| 股票: [{i+1}/{len(stock_codes)}] {code}"
                    )

        logger.info(
            f"TWSE 同步完成: {done} 任務, 跳過 {skipped}, 新增 {new_records} 筆"
        )

    def sync_tpex_dates(self, dates: List[str]):
        """
        Bulk sync TPEX stocks by date (batch API).
        Incremental: skips dates already in DB with sufficient stocks.

        Args:
            dates: List of dates in YYYYMMDD format.
        """
        skipped = 0
        fetched = 0

        logger.info(f"TPEX 同步: {len(dates)} 個日期")

        for i, date in enumerate(dates):
            # Skip if DB already has enough stocks for this date (TPEX ~800+)
            existing_count = self._get_db_stock_count_for_date(date)
            if existing_count >= 700:
                skipped += 1
                continue

            prices = self._fetch_tpex_day(date)
            if prices:
                self._save_to_db(date, prices)
                fetched += 1

            if self.request_delay > 0:
                time.sleep(self.request_delay)

            if (i + 1) % 20 == 0:
                logger.info(
                    f"  TPEX 進度: {i+1}/{len(dates)} | 抓取: {fetched} | 跳過: {skipped}"
                )

        logger.info(f"TPEX 同步完成: 抓取 {fetched}, 跳過 {skipped}")

    # ── API 呼叫 (底層) ────────────────────────────────────

    def _fetch_twse_day(self, date: str) -> Dict[str, float]:
        """Fetch all listed (上市) stocks' close prices via MI_INDEX.
        NOTE: This endpoint frequently times out under load. Prefer STOCK_DAY for reliability.
        """
        try:
            resp = self.session.get(
                TWSE_MI_INDEX_URL,
                params={"response": "json", "date": date, "type": "ALLBUT0999"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("stat") != "OK":
                return {}

            resp_date = data.get("date", "")
            if resp_date and resp_date != date:
                logger.warning(f"TWSE date mismatch: requested {date}, got {resp_date}")
                return {}

            tables = data.get("tables", [])
            prices = {}
            for table in tables:
                rows = table.get("data", [])
                if len(rows) > 500:
                    for row in rows:
                        code = row[0].strip()
                        try:
                            close_str = row[8].replace(",", "").strip()
                            prices[code] = float(close_str)
                        except (ValueError, IndexError):
                            continue
                    break
            return prices

        except Exception as e:
            logger.warning(f"TWSE MI_INDEX failed for {date}: {e}")
            return {}

    def _fetch_tpex_day(self, date: str) -> Dict[str, float]:
        """Fetch all OTC (上櫃) stocks' close prices for a historical date."""
        try:
            roc_date = _to_roc_date(date)
            resp = self.session.get(
                TPEX_HIST_URL,
                params={"l": "zh-tw", "d": roc_date, "se": "EW", "o": "json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            resp_date = data.get("date", "")
            if resp_date and resp_date != date:
                logger.warning(f"TPEX date mismatch: requested {date}, got {resp_date}")
                return {}

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

    # ── 工具方法 ───────────────────────────────────────────

    def fetch_stock_prices(
        self, stock_code: str, dates: List[str]
    ) -> pd.DataFrame:
        """Get close prices for a single stock across multiple dates."""
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
        """Pre-fetch and cache market data for multiple dates."""
        for i, date in enumerate(dates):
            if date not in self._cache:
                logger.info(f"Fetching market prices for {date} ({i+1}/{len(dates)})...")
                self.fetch_market_day(date)
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

    @staticmethod
    def generate_business_days(start: str, end: str) -> List[str]:
        """Generate all weekday dates (YYYYMMDD) between start and end inclusive."""
        dates = pd.bdate_range(start=start, end=end)
        return [d.strftime("%Y%m%d") for d in dates]

    def merge_with_tdcc(
        self, price_df: pd.DataFrame, tdcc_records: List[Dict]
    ) -> pd.DataFrame:
        """Merge price data with TDCC shareholding records by date."""
        if not tdcc_records or price_df.empty:
            return price_df

        tdcc_df = pd.DataFrame(tdcc_records)
        tdcc_df["date"] = pd.to_datetime(tdcc_df["date"], format="%Y%m%d")
        tdcc_df = tdcc_df.set_index("date")

        merged = price_df.join(tdcc_df, how="left")
        return merged
