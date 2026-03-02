"""Main crawler: orchestrates stock list, TDCC scraper, and data storage."""

import argparse
import logging
import sys
from typing import Dict, List, Optional

from crawler.data_manager import DataManager
from crawler.stock_list import get_all_stock_list
from crawler.tdcc_scraper import TDCCScraper

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = "data"


class TDCCCrawler:
    """Orchestrate TDCC data collection for multiple stocks."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR, request_delay: float = 0.5):
        self.data_manager = DataManager(data_dir=data_dir)
        self.scraper = TDCCScraper(request_delay=request_delay)

    def crawl(
        self,
        stocks: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict:
        """
        Crawl TDCC data for given stocks.

        Args:
            stocks: List of stock codes. If None, fetches all from TWSE+TPEX.
            force: If True, re-crawl even if data already exists.

        Returns:
            Stats dict with total_stocks, success, failed, skipped, total_records.
        """
        if stocks is None:
            logger.info("Fetching full stock list from TWSE + TPEX...")
            stocks = get_all_stock_list()

        stats = {
            "total_stocks": len(stocks),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total_records": 0,
        }

        if not stocks:
            return stats

        latest_available = (
            self.scraper.available_dates[0] if self.scraper.available_dates else None
        )

        for i, code in enumerate(stocks, 1):
            # 斷點續爬：已爬到最新日期則跳過
            if not force and latest_available:
                existing_latest = self.data_manager.get_latest_date(code)
                if existing_latest and existing_latest >= latest_available:
                    stats["skipped"] += 1
                    logger.debug(f"[{i}/{len(stocks)}] {code} 已為最新，跳過")
                    continue

            try:
                logger.info(f"[{i}/{len(stocks)}] 正在爬取 {code}...")
                results = self.scraper.query_stock(code)

                if results:
                    self.data_manager.save_records(results)
                    stats["total_records"] += len(results)

                stats["success"] += 1
                logger.info(f"[{i}/{len(stocks)}] {code} 完成，取得 {len(results)} 筆")

            except Exception as e:
                stats["failed"] += 1
                logger.error(f"[{i}/{len(stocks)}] {code} 失敗: {e}")

        logger.info(
            f"爬取完成：成功 {stats['success']}，失敗 {stats['failed']}，"
            f"跳過 {stats['skipped']}，共 {stats['total_records']} 筆資料"
        )
        return stats


def main():
    parser = argparse.ArgumentParser(description="TDCC 大戶持股爬蟲")
    parser.add_argument(
        "--stocks",
        type=str,
        default=None,
        help="指定股票代號（逗號分隔），留空則爬全部",
    )
    parser.add_argument("--output", type=str, default=DEFAULT_DATA_DIR, help="資料輸出目錄")
    parser.add_argument("--delay", type=float, default=0.5, help="每次請求間隔（秒）")
    parser.add_argument("--force", action="store_true", help="強制重新爬取")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細日誌")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    stock_list = args.stocks.split(",") if args.stocks else None

    crawler = TDCCCrawler(data_dir=args.output, request_delay=args.delay)
    crawler.scraper.init_session()

    stats = crawler.crawl(stocks=stock_list, force=args.force)

    print(f"\n=== 爬取結果 ===")
    print(f"目標股票數: {stats['total_stocks']}")
    print(f"成功: {stats['success']}")
    print(f"失敗: {stats['failed']}")
    print(f"跳過: {stats['skipped']}")
    print(f"總資料筆數: {stats['total_records']}")


if __name__ == "__main__":
    main()
