#!/usr/bin/env python3
"""
Full-scale TDCC whale accumulation analysis.

1. Crawl all ~2000+ stocks' TDCC data (latest 12 weeks)
2. Fetch price data for stocks with accumulation patterns
3. Run pattern detection and generate statistics report
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from crawler.main import TDCCCrawler
from crawler.price_fetcher import PriceFetcher
from analysis.pattern_detector import PatternDetector
from analysis.statistics import StatisticsReport
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MAX_DATES = 12  # 最近 12 週（3 個月）


def phase1_crawl():
    """Phase 1: 爬取所有股票的 TDCC 數據"""
    logger.info("=" * 60)
    logger.info("Phase 1: 爬取 TDCC 數據")
    logger.info("=" * 60)

    crawler = TDCCCrawler(data_dir=DATA_DIR, request_delay=0.3)
    crawler.scraper.init_session()

    stats = crawler.crawl(max_dates=MAX_DATES)
    logger.info(f"Phase 1 完成: {stats}")
    return stats


def phase2_analyze():
    """Phase 2: 分析所有有數據的股票"""
    logger.info("=" * 60)
    logger.info("Phase 2: 樣態偵測與統計分析")
    logger.info("=" * 60)

    from crawler.data_manager import DataManager

    dm = DataManager(data_dir=DATA_DIR)
    stocks = dm.get_scraped_stocks()
    logger.info(f"共 {len(stocks)} 檔股票有 TDCC 數據")

    detector = PatternDetector(min_accumulation_weeks=3, min_surge_pct=10.0)
    fetcher = PriceFetcher(request_delay=0.5)

    # 收集 TDCC 日期範圍，擴展為所有營業日（含吃貨結束後的觀察期）
    tdcc_dates = set()
    for code in stocks:
        records = dm.query(stock_code=code)
        for r in records:
            tdcc_dates.add(r["date"])
    tdcc_dates = sorted(tdcc_dates)
    start_date = tdcc_dates[0]
    # 從最早 TDCC 日期到今天，含飆股偵測所需的前看期
    from datetime import datetime
    end_date = datetime.now().strftime("%Y%m%d")
    all_bdays = fetcher.generate_business_days(start_date, end_date)
    logger.info(f"TDCC 日期 {len(tdcc_dates)} 個，展開為 {len(all_bdays)} 個營業日 ({start_date}~{end_date})")

    # 批量預取（每個日期 2 次 API 呼叫：TWSE + TPEX）
    fetcher.fetch_all_dates(all_bdays)
    cached_with_data = sum(1 for v in fetcher._cache.values() if v)
    logger.info(f"收盤價預取完成，{cached_with_data}/{len(all_bdays)} 個日期有資料，共 {sum(len(v) for v in fetcher._cache.values())} 筆價格")

    all_results = []
    stocks_with_acc = 0

    for i, code in enumerate(stocks, 1):
        records = dm.query(stock_code=code)
        if len(records) < 4:
            continue

        tdcc_df = pd.DataFrame(records)

        # 先偵測吃貨樣態（不需要股價）
        accumulations = detector.detect_accumulation(tdcc_df)
        if not accumulations:
            continue

        stocks_with_acc += 1

        # 有吃貨樣態才查股價（從快取取，不再呼叫 API）
        stock_dates = [r["date"] for r in records]
        price_df = fetcher.fetch_stock_prices(code, stock_dates)
        result = detector.analyze_stock(code, tdcc_df, price_df)
        all_results.append(result)

        if i % 200 == 0:
            logger.info(f"分析進度: {i}/{len(stocks)}，已找到 {stocks_with_acc} 檔有吃貨樣態")

    logger.info(f"Phase 2 完成: {len(stocks)} 檔分析，{stocks_with_acc} 檔有吃貨樣態")
    return all_results


def phase3_report(all_results):
    """Phase 3: 生成報告"""
    logger.info("=" * 60)
    logger.info("Phase 3: 生成分析報告")
    logger.info("=" * 60)

    report = StatisticsReport(all_results)
    text = report.format_text()
    print("\n" + text)

    # 存檔
    report_path = os.path.join(DATA_DIR, "analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"報告已儲存: {report_path}")

    # Top gainers CSV
    top = report.top_gainers(n=50)
    if top:
        top_df = pd.DataFrame(top)
        top_path = os.path.join(DATA_DIR, "top_gainers.csv")
        top_df.to_csv(top_path, index=False)
        logger.info(f"Top gainers 已儲存: {top_path}")


def main():
    start_time = time.time()

    phase1_crawl()
    all_results = phase2_analyze()
    phase3_report(all_results)

    elapsed = time.time() - start_time
    logger.info(f"全部完成，耗時 {elapsed/60:.1f} 分鐘")


if __name__ == "__main__":
    main()
