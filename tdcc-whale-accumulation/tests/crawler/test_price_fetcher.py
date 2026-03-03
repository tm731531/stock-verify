import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from crawler.price_fetcher import PriceFetcher, _to_roc_date


class TestRocDateConversion:
    def test_2026(self):
        assert _to_roc_date("20260226") == "115/02/26"

    def test_2025(self):
        assert _to_roc_date("20250307") == "114/03/07"


MOCK_TWSE_RESPONSE = {
    "stat": "OK",
    "data": [
        ["2330", "台積電", "30,000", "50,000,000", "100.00", "105.00", "99.00", "103.00", "+3.00", "10,000"],
        ["0050", "元大台灣50", "10,000", "8,000,000", "80.00", "81.00", "79.00", "80.50", "-0.50", "5,000"],
    ],
}

MOCK_TPEX_RESPONSE = {
    "tables": [
        {
            "data": [
                ["6488", "環球晶", "520.00", "+5.00", "515.00", "525.00", "510.00", "518.00", "1,000,000", "500,000,000", "3,000", "", "", "", "", "", "", "", ""],
            ],
        }
    ],
}


class TestFetchMarketDay:
    def test_twse_prices(self):
        fetcher = PriceFetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_TWSE_RESPONSE
        with patch.object(fetcher.session, "get", return_value=mock_resp):
            prices = fetcher._fetch_twse_day("20260226")
        assert prices["2330"] == 103.0
        assert prices["0050"] == 80.5

    def test_tpex_prices(self):
        fetcher = PriceFetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_TPEX_RESPONSE
        with patch.object(fetcher.session, "get", return_value=mock_resp):
            prices = fetcher._fetch_tpex_day("20260226")
        assert prices["6488"] == 520.0

    def test_fetch_market_day_combines(self):
        fetcher = PriceFetcher()
        with (
            patch.object(fetcher, "_fetch_twse_day", return_value={"2330": 103.0}),
            patch.object(fetcher, "_fetch_tpex_day", return_value={"6488": 520.0}),
        ):
            prices = fetcher.fetch_market_day("20260226")
        assert prices["2330"] == 103.0
        assert prices["6488"] == 520.0

    def test_cache(self):
        fetcher = PriceFetcher()
        with (
            patch.object(fetcher, "_fetch_twse_day", return_value={"2330": 103.0}) as twse_mock,
            patch.object(fetcher, "_fetch_tpex_day", return_value={}),
        ):
            fetcher.fetch_market_day("20260226")
            fetcher.fetch_market_day("20260226")  # should use cache
        twse_mock.assert_called_once()

    def test_twse_error_returns_empty(self):
        fetcher = PriceFetcher()
        with patch.object(fetcher.session, "get", side_effect=Exception("timeout")):
            prices = fetcher._fetch_twse_day("20260226")
        assert prices == {}


class TestFetchStockPrices:
    def test_returns_dataframe(self):
        fetcher = PriceFetcher()
        fetcher._cache = {
            "20260213": {"2330": 100.0},
            "20260220": {"2330": 105.0},
            "20260226": {"2330": 103.0},
        }
        df = fetcher.fetch_stock_prices("2330", ["20260213", "20260220", "20260226"])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "Close" in df.columns
        assert "change_pct" in df.columns

    def test_change_pct_calculated(self):
        fetcher = PriceFetcher()
        fetcher._cache = {
            "20260213": {"2330": 100.0},
            "20260220": {"2330": 110.0},
        }
        df = fetcher.fetch_stock_prices("2330", ["20260213", "20260220"])
        assert abs(df["change_pct"].iloc[1] - 10.0) < 0.01

    def test_missing_stock_returns_empty(self):
        fetcher = PriceFetcher()
        fetcher._cache = {"20260226": {"0050": 80.0}}
        df = fetcher.fetch_stock_prices("9999", ["20260226"])
        assert len(df) == 0


class TestGenerateBusinessDays:
    def test_weekdays_only(self):
        days = PriceFetcher.generate_business_days("20260223", "20260227")
        assert days == ["20260223", "20260224", "20260225", "20260226", "20260227"]

    def test_skips_weekend(self):
        # 2026-02-28 is Saturday, 2026-03-01 is Sunday
        days = PriceFetcher.generate_business_days("20260227", "20260302")
        assert "20260228" not in days
        assert "20260301" not in days
        assert days == ["20260227", "20260302"]


class TestFetchAllDates:
    def test_prefetches_all_dates(self):
        fetcher = PriceFetcher(request_delay=0)
        call_count = 0

        def mock_fetch(date):
            nonlocal call_count
            call_count += 1
            return {f"2330": 100.0 + call_count}

        with patch.object(fetcher, "fetch_market_day", side_effect=mock_fetch):
            fetcher.fetch_all_dates(["20260213", "20260220", "20260226"])
        assert call_count == 3

    def test_skips_cached_dates(self):
        fetcher = PriceFetcher(request_delay=0)
        fetcher._cache["20260213"] = {"2330": 100.0}

        with patch.object(fetcher, "fetch_market_day", return_value={"2330": 105.0}) as mock:
            fetcher.fetch_all_dates(["20260213", "20260220"])
        mock.assert_called_once_with("20260220")


class TestMergeWithTdcc:
    def test_merge(self):
        fetcher = PriceFetcher()
        fetcher._cache = {
            "20260213": {"2330": 100.0},
            "20260220": {"2330": 105.0},
        }
        price_df = fetcher.fetch_stock_prices("2330", ["20260213", "20260220"])
        tdcc_records = [{"date": "20260213", "ratio_400_above": 89.0}]
        merged = fetcher.merge_with_tdcc(price_df, tdcc_records)
        assert "ratio_400_above" in merged.columns
        assert merged["ratio_400_above"].notna().sum() == 1


@pytest.mark.integration
class TestPriceFetcherIntegration:
    def test_fetch_twse_real(self):
        fetcher = PriceFetcher()
        prices = fetcher._fetch_twse_day("20260226")
        assert len(prices) > 1000
        assert "2330" in prices
        assert prices["2330"] > 0

    def test_fetch_tpex_real(self):
        fetcher = PriceFetcher()
        prices = fetcher._fetch_tpex_day("20260226")
        assert len(prices) > 500

    def test_fetch_market_day_real(self):
        fetcher = PriceFetcher()
        prices = fetcher.fetch_market_day("20260226")
        assert len(prices) > 1500  # TWSE + TPEX
        assert "2330" in prices  # 上市
