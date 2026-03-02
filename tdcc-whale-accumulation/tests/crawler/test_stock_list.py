import pytest
from unittest.mock import patch, MagicMock
from crawler.stock_list import get_twse_stock_list, get_tpex_stock_list, get_all_stock_list


# --- Unit tests with mocked API ---


class TestGetTwseStockList:
    def test_returns_list(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stat": "OK",
            "data": [
                ["2330", "台積電", "1", "2", "3", "4", "5", "6", "7", "8"],
                ["0050", "元大台灣50", "1", "2", "3", "4", "5", "6", "7", "8"],
            ],
        }
        with patch("crawler.stock_list.requests.get", return_value=mock_resp):
            stocks = get_twse_stock_list()
        assert isinstance(stocks, list)
        assert len(stocks) == 2
        assert "2330" in stocks
        assert "0050" in stocks

    def test_returns_sorted(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stat": "OK",
            "data": [
                ["2330", "台積電", "1", "2", "3", "4", "5", "6", "7", "8"],
                ["1101", "台泥", "1", "2", "3", "4", "5", "6", "7", "8"],
            ],
        }
        with patch("crawler.stock_list.requests.get", return_value=mock_resp):
            stocks = get_twse_stock_list()
        assert stocks == sorted(stocks)

    def test_handles_api_error(self):
        with patch("crawler.stock_list.requests.get", side_effect=Exception("timeout")):
            stocks = get_twse_stock_list()
        assert stocks == []

    def test_handles_missing_data_key(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"stat": "NO_DATA"}
        with patch("crawler.stock_list.requests.get", return_value=mock_resp):
            stocks = get_twse_stock_list()
        assert stocks == []


class TestGetTpexStockList:
    def test_returns_list(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"SecuritiesCompanyCode": "5483", "CompanyName": "中美晶"},
            {"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶"},
        ]
        with patch("crawler.stock_list.requests.get", return_value=mock_resp):
            stocks = get_tpex_stock_list()
        assert isinstance(stocks, list)
        assert "5483" in stocks
        assert "6488" in stocks

    def test_handles_api_error(self):
        with patch("crawler.stock_list.requests.get", side_effect=Exception("fail")):
            stocks = get_tpex_stock_list()
        assert stocks == []


class TestGetAllStockList:
    def test_combines_twse_and_tpex(self):
        with (
            patch("crawler.stock_list.get_twse_stock_list", return_value=["2330", "0050"]),
            patch("crawler.stock_list.get_tpex_stock_list", return_value=["5483", "6488"]),
        ):
            all_stocks = get_all_stock_list()
        assert len(all_stocks) == 4
        assert all_stocks == sorted(all_stocks)

    def test_deduplicates(self):
        with (
            patch("crawler.stock_list.get_twse_stock_list", return_value=["2330", "0050"]),
            patch("crawler.stock_list.get_tpex_stock_list", return_value=["2330", "6488"]),
        ):
            all_stocks = get_all_stock_list()
        assert len(all_stocks) == 3  # deduplicated


# --- Integration test (hits real API) ---


@pytest.mark.integration
class TestStockListIntegration:
    def test_twse_real_api(self):
        stocks = get_twse_stock_list()
        assert len(stocks) > 500
        assert "2330" in stocks  # TSMC must exist

    def test_tpex_real_api(self):
        stocks = get_tpex_stock_list()
        assert len(stocks) > 300

    def test_all_stocks_real_api(self):
        all_stocks = get_all_stock_list()
        assert len(all_stocks) > 1000
        # Code format: 4-6 alphanumeric characters
        for code in all_stocks:
            assert 4 <= len(code) <= 6, f"Unexpected code length: {code}"
