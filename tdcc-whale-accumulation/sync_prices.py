#!/usr/bin/env python3
"""
Sync daily prices into SQLite for the full TDCC analysis window.

Two data sources:
  - TPEX (上櫃): batch API per date, ~800 stocks/day
  - TWSE (上市): STOCK_DAY per stock per month, ~1300 stocks × 12 months

Both are incremental - skip data already in DB.
"""
import sys, os, logging, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from crawler.price_fetcher import PriceFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "tdcc_holdings.db")


def get_tdcc_range():
    """Get date range and stock list from TDCC holdings."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    min_date, max_date = conn.execute("SELECT MIN(date), MAX(date) FROM holdings").fetchone()
    stocks = [r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM holdings ORDER BY stock_code").fetchall()]
    conn.close()
    return min_date, max_date, stocks


def report(fetcher):
    """Print completeness report."""
    conn = sqlite3.connect(DB_PATH, timeout=30)

    total = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    n_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM daily_prices").fetchone()[0]
    n_stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM daily_prices").fetchone()[0]

    tdcc_dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM holdings ORDER BY date").fetchall()]
    price_dates = set(r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_prices").fetchall())
    missing_tdcc = sorted(set(tdcc_dates) - price_dates)

    date_counts = conn.execute(
        "SELECT date, COUNT(*) as n FROM daily_prices GROUP BY date ORDER BY date"
    ).fetchall()
    conn.close()

    logger.info("=" * 60)
    logger.info("股價資料完整性報告")
    logger.info("=" * 60)
    logger.info(f"  總記錄: {total:,}")
    logger.info(f"  日期數: {n_dates}")
    logger.info(f"  股票數: {n_stocks}")

    if date_counts:
        avg_n = sum(r[1] for r in date_counts) / len(date_counts)
        logger.info(f"  平均每天: {avg_n:.0f} 檔")

    logger.info(f"  TDCC 日期覆蓋: {len(tdcc_dates) - len(missing_tdcc)}/{len(tdcc_dates)}")
    if missing_tdcc:
        logger.info(f"  缺少 TDCC 日期: {missing_tdcc[:5]}{'...' if len(missing_tdcc) > 5 else ''}")

    # Sample dates
    if date_counts:
        logger.info(f"\n  前3天:")
        for d, n in date_counts[:3]:
            logger.info(f"    {d}: {n} 檔")
        logger.info(f"  後3天:")
        for d, n in date_counts[-3:]:
            logger.info(f"    {d}: {n} 檔")


def main():
    min_date, max_date, tdcc_stocks = get_tdcc_range()
    start_month = min_date[:6]  # YYYYMM
    end_month = max_date[:6]

    logger.info(f"TDCC 範圍: {min_date} ~ {max_date}")
    logger.info(f"月份範圍: {start_month} ~ {end_month}")
    logger.info(f"TDCC 股票數: {len(tdcc_stocks)}")

    fetcher = PriceFetcher(request_delay=1.0, db_path=DB_PATH)

    # ── Phase A: TPEX 上櫃 (batch by date) ──
    logger.info("\n" + "=" * 60)
    logger.info("Phase A: TPEX 上櫃股價同步 (batch by date)")
    logger.info("=" * 60)

    all_bdays = fetcher.generate_business_days(min_date, max_date)
    logger.info(f"營業日: {len(all_bdays)} 天")
    fetcher.sync_tpex_dates(all_bdays)

    # ── Phase B: TWSE 上市 (per stock per month) ──
    logger.info("\n" + "=" * 60)
    logger.info("Phase B: TWSE 上市股價同步 (STOCK_DAY)")
    logger.info("=" * 60)

    # Get TWSE stock list
    twse_stocks = fetcher.get_twse_listed_stocks()
    if not twse_stocks:
        logger.error("無法取得 TWSE 股票清單!")
        return

    # Only sync stocks that are in TDCC holdings
    tdcc_set = set(tdcc_stocks)
    twse_in_tdcc = [s for s in twse_stocks if s in tdcc_set]
    logger.info(f"TWSE 上市: {len(twse_stocks)} | 在 TDCC 中: {len(twse_in_tdcc)}")

    fetcher.sync_twse_stocks(twse_in_tdcc, start_month, end_month)

    # ── Report ──
    report(fetcher)


if __name__ == "__main__":
    main()
