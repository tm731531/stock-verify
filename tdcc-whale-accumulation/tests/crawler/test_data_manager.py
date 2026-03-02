import os
import sqlite3
import tempfile

import pandas as pd
import pytest
from crawler.data_manager import DataManager

# 模擬爬蟲回傳的資料
SAMPLE_RECORDS = [
    {
        "stock_code": "2330",
        "date": "20260226",
        "ratio_400_above": 89.05,
        "ratio_1000_above": 86.33,
        "total_holders": 2014899,
        "tiers": [],
    },
    {
        "stock_code": "2330",
        "date": "20260213",
        "ratio_400_above": 89.06,
        "ratio_1000_above": 86.34,
        "total_holders": 1982676,
        "tiers": [],
    },
    {
        "stock_code": "2317",
        "date": "20260226",
        "ratio_400_above": 68.76,
        "ratio_1000_above": 65.91,
        "total_holders": 1109444,
        "tiers": [],
    },
]


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def manager(tmp_dir):
    return DataManager(data_dir=tmp_dir)


class TestDataManagerSaveCSV:
    def test_save_creates_csv(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        csv_path = os.path.join(tmp_dir, "tdcc_data.csv")
        assert os.path.exists(csv_path)

    def test_csv_has_correct_rows(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        df = pd.read_csv(os.path.join(tmp_dir, "tdcc_data.csv"))
        assert len(df) == 3

    def test_csv_has_correct_columns(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        df = pd.read_csv(os.path.join(tmp_dir, "tdcc_data.csv"))
        expected_cols = {"stock_code", "date", "ratio_400_above", "ratio_1000_above", "total_holders"}
        assert expected_cols.issubset(set(df.columns))

    def test_append_deduplicates(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        # 再存一次同樣的資料
        manager.save_records(SAMPLE_RECORDS)
        df = pd.read_csv(os.path.join(tmp_dir, "tdcc_data.csv"))
        assert len(df) == 3  # 不應重複

    def test_append_adds_new_records(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS[:2])
        manager.save_records(SAMPLE_RECORDS[2:])
        df = pd.read_csv(os.path.join(tmp_dir, "tdcc_data.csv"))
        assert len(df) == 3


class TestDataManagerSQLite:
    def test_save_creates_db(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        db_path = os.path.join(tmp_dir, "tdcc_holdings.db")
        assert os.path.exists(db_path)

    def test_db_has_correct_rows(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        db_path = os.path.join(tmp_dir, "tdcc_holdings.db")
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        conn.close()
        assert count == 3

    def test_db_deduplicates(self, manager, tmp_dir):
        manager.save_records(SAMPLE_RECORDS)
        manager.save_records(SAMPLE_RECORDS)
        db_path = os.path.join(tmp_dir, "tdcc_holdings.db")
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        conn.close()
        assert count == 3


class TestDataManagerQuery:
    def test_query_by_stock(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        results = manager.query(stock_code="2330")
        assert len(results) == 2
        assert all(r["stock_code"] == "2330" for r in results)

    def test_query_by_date_range(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        results = manager.query(date_start="20260213", date_end="20260226")
        assert len(results) == 3

    def test_query_by_stock_and_date(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        results = manager.query(stock_code="2330", date_start="20260226")
        assert len(results) == 1

    def test_query_returns_sorted_by_date(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        results = manager.query(stock_code="2330")
        dates = [r["date"] for r in results]
        assert dates == sorted(dates)

    def test_query_empty_result(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        results = manager.query(stock_code="9999")
        assert results == []

    def test_get_scraped_stocks(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        stocks = manager.get_scraped_stocks()
        assert set(stocks) == {"2317", "2330"}

    def test_get_latest_date_for_stock(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        latest = manager.get_latest_date("2330")
        assert latest == "20260226"

    def test_get_latest_date_unknown_stock(self, manager):
        manager.save_records(SAMPLE_RECORDS)
        latest = manager.get_latest_date("9999")
        assert latest is None
