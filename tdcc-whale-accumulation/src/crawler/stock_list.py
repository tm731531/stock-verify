"""Fetch Taiwan stock codes from TWSE and TPEX official APIs."""

import logging
from typing import List

import requests

logger = logging.getLogger(__name__)

TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
REQUEST_TIMEOUT = 15


def get_twse_stock_list() -> List[str]:
    """Fetch listed (上市) stock codes from TWSE."""
    try:
        resp = requests.get(
            TWSE_URL,
            params={"response": "json", "date": "20240101"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" not in data:
            logger.warning("TWSE API returned no data")
            return []

        codes = [item[0].strip() for item in data["data"]]
        return sorted(codes)

    except Exception as e:
        logger.error(f"Error fetching TWSE stock list: {e}")
        return []


def get_tpex_stock_list() -> List[str]:
    """Fetch OTC (上櫃) stock codes from TPEX."""
    try:
        resp = requests.get(TPEX_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        codes = [item["SecuritiesCompanyCode"].strip() for item in data]
        return sorted(codes)

    except Exception as e:
        logger.error(f"Error fetching TPEX stock list: {e}")
        return []


def get_all_stock_list() -> List[str]:
    """Fetch all Taiwan stock codes (TWSE + TPEX), deduplicated and sorted."""
    twse = get_twse_stock_list()
    tpex = get_tpex_stock_list()
    return sorted(set(twse + tpex))
