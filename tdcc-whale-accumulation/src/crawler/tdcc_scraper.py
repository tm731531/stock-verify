"""TDCC shareholding distribution scraper using requests (no Selenium needed)."""

import logging
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
REQUEST_TIMEOUT = 15
# 400張 = 400,000 shares. Tiers 12-15 cover 400,001+ shares.
WHALE_TIER_START = 12
# 1000張 = 1,000,001+ shares. Tier 15.
MEGA_WHALE_TIER = 15


class TDCCScraper:
    """Scrape TDCC shareholding distribution data via HTTP POST."""

    def __init__(self, request_delay: float = 0.5):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        self.token: Optional[str] = None
        self.available_dates: List[str] = []
        self.request_delay = request_delay

    def init_session(self) -> None:
        """Fetch initial page to obtain CSRF token and available dates."""
        resp = self.session.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        token_input = soup.find("input", {"id": "SYNCHRONIZER_TOKEN"})
        if token_input:
            self.token = token_input.get("value")

        date_select = soup.find("select", {"name": "scaDate"})
        if date_select:
            self.available_dates = [
                opt.get("value")
                for opt in date_select.find_all("option")
                if opt.get("value")
            ]

        logger.info(
            f"Session initialized: {len(self.available_dates)} dates available, "
            f"token={self.token[:8]}..."
        )

    def query_stock(
        self, stock_code: str, dates: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Query shareholding distribution for a stock across dates.

        Args:
            stock_code: Stock ticker (e.g., '2330')
            dates: Specific dates to query. Defaults to all available dates.

        Returns:
            List of dicts with date, stock_code, ratio_400_above, etc.
        """
        target_dates = dates or self.available_dates
        results = []

        for date in target_dates:
            form_data = {
                "SYNCHRONIZER_TOKEN": self.token,
                "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                "method": "submit",
                "firDate": date,
                "scaDate": date,
                "sqlMethod": "StockNo",
                "stockNo": stock_code,
                "stockName": "",
            }

            try:
                resp = self.session.post(
                    BASE_URL, data=form_data, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                parsed = self._parse_result_page(resp.text)

                if parsed:
                    parsed["stock_code"] = stock_code
                    parsed["date"] = date
                    results.append(parsed)
                else:
                    logger.debug(f"No data for {stock_code} on {date}")

            except Exception as e:
                logger.warning(f"Error querying {stock_code} on {date}: {e}")

            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return results

    def _parse_result_page(self, html: str) -> Optional[Dict]:
        """
        Parse the HTML result page and extract shareholding distribution.

        Returns None if no data table found.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Update CSRF token for next request
        token_input = soup.find("input", {"id": "SYNCHRONIZER_TOKEN"})
        if token_input:
            self.token = token_input.get("value")

        # Find the shareholding distribution table (the one with >5 rows)
        tables = soup.find_all("table")
        data_table = None
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) > 5:
                data_table = table
                break

        if not data_table:
            return None

        rows = data_table.find_all("tr")
        tiers = []
        total_holders = 0

        for row in rows[1:]:  # Skip header
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            tier_idx_text = cells[0].get_text(strip=True)
            tier_name = cells[1].get_text(strip=True)
            holders_text = cells[2].get_text(strip=True)
            shares_text = cells[3].get_text(strip=True)
            ratio_text = cells[4].get_text(strip=True)

            # Skip adjustment and total rows
            if "差異" in tier_name or "合" in tier_name:
                if "合" in tier_name and holders_text:
                    total_holders = int(holders_text.replace(",", ""))
                continue

            try:
                tier_idx = int(tier_idx_text)
                ratio = float(ratio_text)
                shares = int(shares_text.replace(",", ""))
                holders = int(holders_text.replace(",", "")) if holders_text else 0
            except (ValueError, TypeError):
                continue

            tiers.append(
                {
                    "tier_index": tier_idx,
                    "tier_name": tier_name,
                    "holders": holders,
                    "shares": shares,
                    "ratio": ratio,
                }
            )

        if not tiers:
            return None

        # Calculate whale ratios
        ratio_400_above = sum(
            t["ratio"] for t in tiers if t["tier_index"] >= WHALE_TIER_START
        )
        ratio_1000_above = sum(
            t["ratio"] for t in tiers if t["tier_index"] >= MEGA_WHALE_TIER
        )

        return {
            "tiers": tiers,
            "ratio_400_above": round(ratio_400_above, 2),
            "ratio_1000_above": round(ratio_1000_above, 2),
            "total_holders": total_holders,
        }
