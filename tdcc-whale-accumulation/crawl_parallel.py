#!/usr/bin/env python3
"""Parallel TDCC crawler - split stocks into batches and crawl concurrently."""

import logging
import os
import sqlite3
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from crawler.stock_list import get_all_stock_list
from crawler.main import TDCCCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "tdcc_holdings.db")


def get_incomplete_stocks():
    """Find stocks with < 51 weeks of data."""
    stocks = get_all_stock_list()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()

    incomplete = []
    for s in stocks:
        c.execute("SELECT COUNT(DISTINCT date) FROM holdings WHERE stock_code=?", (s,))
        count = c.fetchone()[0]
        if count < 51:
            incomplete.append(s)

    conn.close()
    return incomplete


def crawl_batch(worker_id, stocks):
    """Crawl a batch of stocks (skip CSV for parallel safety)."""
    log = logging.getLogger(f"worker-{worker_id}")
    log.info(f"啟動，負責 {len(stocks)} 檔")

    crawler = TDCCCrawler(data_dir=DATA_DIR, request_delay=0.3)
    crawler.scraper.init_session()

    stats = crawler.crawl(
        stocks=stocks,
        max_dates=51,
        incremental=True,
        skip_csv=True,
    )

    log.info(f"完成: {stats}")
    return stats


def export_csv():
    """Export SQLite to CSV after parallel crawl completes."""
    csv_path = os.path.join(DATA_DIR, "tdcc_data.csv")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    df = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    conn.close()
    df.to_csv(csv_path, index=False)
    logger.info(f"CSV 匯出完成: {len(df)} 筆 → {csv_path}")


if __name__ == "__main__":
    import multiprocessing as mp

    N_WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 2

    incomplete = get_incomplete_stocks()
    logger.info(f"需補爬: {len(incomplete)} 檔，使用 {N_WORKERS} 路平行")

    if not incomplete:
        logger.info("全部股票已有 51 週資料，無需補爬！")
        sys.exit(0)

    # Split into batches
    batch_size = len(incomplete) // N_WORKERS + 1
    batches = []
    for i in range(N_WORKERS):
        batch = incomplete[i * batch_size : (i + 1) * batch_size]
        if batch:
            batches.append(batch)
            logger.info(f"Worker {i}: {len(batch)} 檔")

    # Run in parallel
    start = time.time()

    with mp.Pool(len(batches)) as pool:
        results = pool.starmap(crawl_batch, [(i, b) for i, b in enumerate(batches)])

    elapsed = time.time() - start

    # Summary
    total_success = sum(r["success"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_records = sum(r["total_records"] for r in results)

    logger.info("=" * 60)
    logger.info(f"全部完成！耗時 {elapsed / 60:.1f} 分鐘")
    logger.info(f"成功: {total_success}, 失敗: {total_failed}, 跳過: {total_skipped}, 新增: {total_records} 筆")
    logger.info("=" * 60)

    # Export CSV from SQLite
    export_csv()

    # Verify
    conn = sqlite3.connect(DB_PATH, timeout=30)
    counts = conn.execute(
        "SELECT date, COUNT(*) FROM holdings GROUP BY date ORDER BY date"
    ).fetchall()
    conn.close()

    full = [r for r in counts if r[1] > 1000]
    logger.info(f"全量日期（>1000檔）: {len(full)} / {len(counts)} 週")
    for d, n in counts[-5:]:
        logger.info(f"  {d}: {n} 檔")
