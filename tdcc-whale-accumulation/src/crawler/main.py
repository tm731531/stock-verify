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
SESSION_REINIT_INTERVAL = 500  # 每 N 檔重新初始化 session


class TDCCCrawler:
    """Orchestrate TDCC data collection for multiple stocks."""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR, request_delay: float = 0.5):
        self.data_manager = DataManager(data_dir=data_dir)
        self.scraper = TDCCScraper(request_delay=request_delay)

    def crawl(
        self,
        stocks: Optional[List[str]] = None,
        force: bool = False,
        max_dates: Optional[int] = None,
        incremental: bool = True,
        batch_start: int = 0,
        batch_size: Optional[int] = None,
        skip_csv: bool = False,
    ) -> Dict:
        """
        Crawl TDCC data for given stocks.

        Args:
            stocks: List of stock codes. If None, fetches all from TWSE+TPEX.
            force: If True, re-crawl even if data already exists.
            max_dates: Limit number of dates to query per stock (latest N).
            incremental: If True, only query dates not already in DB.
            batch_start: Start index for batch processing.
            batch_size: Number of stocks per batch (None = all).

        Returns:
            Stats dict with total_stocks, success, failed, skipped, total_records.
        """
        if stocks is None:
            logger.info("Fetching full stock list from TWSE + TPEX...")
            stocks = get_all_stock_list()

        # 分批處理
        total_count = len(stocks)
        if batch_size:
            stocks = stocks[batch_start:batch_start + batch_size]
            logger.info(f"分批模式: 從第 {batch_start} 檔開始，處理 {len(stocks)} 檔 (共 {total_count} 檔)")

        stats = {
            "total_stocks": len(stocks),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total_records": 0,
            "incremental_saved": 0,
        }

        if not stocks:
            return stats

        # 限制查詢日期數
        all_query_dates = self.scraper.available_dates
        if max_dates and max_dates < len(all_query_dates):
            all_query_dates = all_query_dates[:max_dates]
            logger.info(f"限制查詢最近 {max_dates} 個日期 ({len(all_query_dates)} 個)")

        all_query_dates_set = set(all_query_dates)

        for i, code in enumerate(stocks, 1):
            # 每 SESSION_REINIT_INTERVAL 檔重新初始化 session 避免 timeout
            if i > 1 and (i - 1) % SESSION_REINIT_INTERVAL == 0:
                logger.info(f"已處理 {i-1} 檔，重新初始化 session...")
                self.scraper.init_session()

            # 增量模式：只查詢 DB 中缺少的日期
            if incremental and not force:
                existing_dates = set(self.data_manager.get_existing_dates(code))
                missing_dates = [d for d in all_query_dates if d not in existing_dates]

                if not missing_dates:
                    stats["skipped"] += 1
                    if i % 200 == 0:
                        logger.debug(f"[{i}/{len(stocks)}] {code} 已有全部 {len(all_query_dates)} 個日期，跳過")
                    continue

                query_dates = missing_dates
                logger.info(
                    f"[{i}/{len(stocks)}] {code}: 已有 {len(existing_dates)} 個日期，"
                    f"需補爬 {len(missing_dates)} 個"
                )
            else:
                # 非增量：檢查最新日期跳過
                latest_available = all_query_dates[0] if all_query_dates else None
                if not force and latest_available:
                    existing_latest = self.data_manager.get_latest_date(code)
                    if existing_latest and existing_latest >= latest_available:
                        stats["skipped"] += 1
                        continue
                query_dates = all_query_dates

            try:
                results = self.scraper.query_stock(code, dates=query_dates)

                if results:
                    self.data_manager.save_records(results, skip_csv=skip_csv)
                    stats["total_records"] += len(results)

                stats["success"] += 1

                if i % 50 == 0 or i == len(stocks):
                    logger.info(
                        f"進度: {i}/{len(stocks)} ({i/len(stocks)*100:.0f}%) "
                        f"成功={stats['success']} 失敗={stats['failed']} "
                        f"跳過={stats['skipped']} 累計={stats['total_records']}筆"
                    )

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
    parser.add_argument("--delay", type=float, default=0.2, help="每次請求間隔（秒）")
    parser.add_argument("--max-dates", type=int, default=None, help="每檔股票最多查詢幾個日期（預設全部）")
    parser.add_argument("--force", action="store_true", help="強制重新爬取")
    parser.add_argument("--no-incremental", action="store_true", help="關閉增量模式（預設開啟）")
    parser.add_argument("--batch-start", type=int, default=0, help="分批起始索引")
    parser.add_argument("--batch-size", type=int, default=None, help="每批處理股票數")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細日誌")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    stock_list = args.stocks.split(",") if args.stocks else None

    crawler = TDCCCrawler(data_dir=args.output, request_delay=args.delay)
    crawler.scraper.init_session()

    stats = crawler.crawl(
        stocks=stock_list,
        force=args.force,
        max_dates=args.max_dates,
        incremental=not args.no_incremental,
        batch_start=args.batch_start,
        batch_size=args.batch_size,
    )

    print(f"\n=== 爬取結果 ===")
    print(f"目標股票數: {stats['total_stocks']}")
    print(f"成功: {stats['success']}")
    print(f"失敗: {stats['failed']}")
    print(f"跳過: {stats['skipped']}")
    print(f"總資料筆數: {stats['total_records']}")


if __name__ == "__main__":
    main()
