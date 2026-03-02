import tempfile

import pytest
from unittest.mock import patch, MagicMock, call
from crawler.main import TDCCCrawler


MOCK_SCRAPER_RESULT = [
    {
        "stock_code": "2330",
        "date": "20260226",
        "ratio_400_above": 89.05,
        "ratio_1000_above": 86.33,
        "total_holders": 2014899,
        "tiers": [],
    },
]


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestTDCCCrawler:
    def test_init(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        assert crawler.data_manager is not None
        assert crawler.scraper is not None

    def test_crawl_stocks_calls_scraper(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.return_value = MOCK_SCRAPER_RESULT

        stats = crawler.crawl(stocks=["2330"])

        crawler.scraper.query_stock.assert_called_once_with("2330", dates=["20260226"])
        assert stats["total_stocks"] == 1
        assert stats["success"] == 1
        assert stats["failed"] == 0

    def test_crawl_multiple_stocks(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.return_value = MOCK_SCRAPER_RESULT

        stats = crawler.crawl(stocks=["2330", "2317", "0050"])

        assert crawler.scraper.query_stock.call_count == 3
        assert stats["total_stocks"] == 3
        assert stats["success"] == 3

    def test_crawl_handles_failure(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.side_effect = [MOCK_SCRAPER_RESULT, Exception("timeout"), MOCK_SCRAPER_RESULT]

        stats = crawler.crawl(stocks=["2330", "9999", "0050"])

        assert stats["success"] == 2
        assert stats["failed"] == 1

    def test_crawl_saves_data(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.return_value = MOCK_SCRAPER_RESULT

        crawler.crawl(stocks=["2330"])

        # 資料應已存入 DataManager
        results = crawler.data_manager.query(stock_code="2330")
        assert len(results) == 1
        assert results[0]["ratio_400_above"] == 89.05

    def test_crawl_skips_already_complete(self, tmp_dir):
        """已爬過且最新日期與可用日期一致的股票應跳過"""
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.return_value = MOCK_SCRAPER_RESULT

        # 先爬一次
        crawler.crawl(stocks=["2330"])
        crawler.scraper.query_stock.reset_mock()

        # 再爬一次，應跳過
        stats = crawler.crawl(stocks=["2330"])
        crawler.scraper.query_stock.assert_not_called()
        assert stats["skipped"] == 1

    def test_crawl_empty_list(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        stats = crawler.crawl(stocks=[])
        assert stats["total_stocks"] == 0

    def test_crawl_returns_total_records(self, tmp_dir):
        crawler = TDCCCrawler(data_dir=tmp_dir)
        crawler.scraper = MagicMock()
        crawler.scraper.available_dates = ["20260226"]
        crawler.scraper.query_stock.return_value = MOCK_SCRAPER_RESULT

        stats = crawler.crawl(stocks=["2330"])
        assert stats["total_records"] == 1
