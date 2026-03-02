import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from crawler.tdcc_scraper import TDCCScraper

# Sample HTML for the initial page (with CSRF token and date dropdown)
SAMPLE_INIT_HTML = """
<html><body>
<form action="/portal/zh/smWeb/qryStock" method="post">
  <input type="hidden" name="SYNCHRONIZER_TOKEN" id="SYNCHRONIZER_TOKEN" value="test-token-123"/>
  <input type="hidden" name="SYNCHRONIZER_URI" id="SYNCHRONIZER_URI" value="/portal/zh/smWeb/qryStock"/>
  <select name="scaDate" id="scaDate">
    <option value="20260226">20260226</option>
    <option value="20260213">20260213</option>
    <option value="20260206">20260206</option>
  </select>
</form>
</body></html>
"""

# Sample HTML for a query result page (shareholding distribution)
SAMPLE_RESULT_HTML = """
<html><body>
<input type="hidden" name="SYNCHRONIZER_TOKEN" id="SYNCHRONIZER_TOKEN" value="new-token-456"/>
<table><tr><td>metadata</td></tr></table>
<table>
<tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr>
<tr><td>1</td><td>1-999</td><td>100,000</td><td>50,000,000</td><td>5.00</td></tr>
<tr><td>2</td><td>1,000-5,000</td><td>50,000</td><td>100,000,000</td><td>10.00</td></tr>
<tr><td>3</td><td>5,001-10,000</td><td>10,000</td><td>70,000,000</td><td>7.00</td></tr>
<tr><td>4</td><td>10,001-15,000</td><td>5,000</td><td>60,000,000</td><td>6.00</td></tr>
<tr><td>5</td><td>15,001-20,000</td><td>3,000</td><td>50,000,000</td><td>5.00</td></tr>
<tr><td>6</td><td>20,001-30,000</td><td>2,000</td><td>50,000,000</td><td>5.00</td></tr>
<tr><td>7</td><td>30,001-40,000</td><td>1,000</td><td>35,000,000</td><td>3.50</td></tr>
<tr><td>8</td><td>40,001-50,000</td><td>500</td><td>22,500,000</td><td>2.25</td></tr>
<tr><td>9</td><td>50,001-100,000</td><td>400</td><td>28,000,000</td><td>2.80</td></tr>
<tr><td>10</td><td>100,001-200,000</td><td>200</td><td>28,000,000</td><td>2.80</td></tr>
<tr><td>11</td><td>200,001-400,000</td><td>100</td><td>28,000,000</td><td>2.80</td></tr>
<tr><td>12</td><td>400,001-600,000</td><td>50</td><td>25,000,000</td><td>2.50</td></tr>
<tr><td>13</td><td>600,001-800,000</td><td>30</td><td>21,000,000</td><td>2.10</td></tr>
<tr><td>14</td><td>800,001-1,000,000</td><td>20</td><td>18,000,000</td><td>1.80</td></tr>
<tr><td>15</td><td>1,000,001以上</td><td>10</td><td>434,500,000</td><td>43.45</td></tr>
<tr><td>16</td><td>差異數調整（說明4）</td><td></td><td>0</td><td>0.00</td></tr>
<tr><td>17</td><td>合　計</td><td>172,310</td><td>1,000,000,000</td><td>100.00</td></tr>
</table>
</body></html>
"""

# Result page with no data table (stock not found)
SAMPLE_NO_DATA_HTML = """
<html><body>
<input type="hidden" name="SYNCHRONIZER_TOKEN" id="SYNCHRONIZER_TOKEN" value="new-token-789"/>
<table><tr><td>metadata</td></tr></table>
</body></html>
"""


class TestTDCCScraperInit:
    def test_creates_session(self):
        scraper = TDCCScraper()
        assert scraper.session is not None

    def test_fetches_available_dates(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_INIT_HTML
        with patch("crawler.tdcc_scraper.requests.Session") as MockSession:
            MockSession.return_value.get.return_value = mock_resp
            scraper = TDCCScraper()
            scraper.init_session()
        assert scraper.available_dates == ["20260226", "20260213", "20260206"]
        assert scraper.token == "test-token-123"


class TestTDCCScraperParseResult:
    def setup_method(self):
        self.scraper = TDCCScraper()

    def test_parse_shareholding_table(self):
        result = self.scraper._parse_result_page(SAMPLE_RESULT_HTML)
        assert result is not None
        assert len(result["tiers"]) == 15  # 15 actual tiers (excludes adjustment + total)
        assert result["tiers"][0]["tier_name"] == "1-999"
        assert result["tiers"][0]["ratio"] == 5.0

    def test_parse_400_above_ratio(self):
        result = self.scraper._parse_result_page(SAMPLE_RESULT_HTML)
        # Tiers 12-15 (400,001+): 2.50 + 2.10 + 1.80 + 43.45 = 49.85
        assert abs(result["ratio_400_above"] - 49.85) < 0.01

    def test_parse_1000_above_ratio(self):
        result = self.scraper._parse_result_page(SAMPLE_RESULT_HTML)
        assert abs(result["ratio_1000_above"] - 43.45) < 0.01

    def test_parse_total_holders(self):
        result = self.scraper._parse_result_page(SAMPLE_RESULT_HTML)
        assert result["total_holders"] == 172310

    def test_parse_no_data_returns_none(self):
        result = self.scraper._parse_result_page(SAMPLE_NO_DATA_HTML)
        assert result is None

    def test_new_token_extracted(self):
        self.scraper._parse_result_page(SAMPLE_RESULT_HTML)
        assert self.scraper.token == "new-token-456"


class TestTDCCScraperQueryStock:
    def setup_method(self):
        self.scraper = TDCCScraper()
        self.scraper.token = "test-token"
        self.scraper.available_dates = ["20260226", "20260213"]

    def test_query_single_date(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_RESULT_HTML
        self.scraper.session = MagicMock()
        self.scraper.session.post.return_value = mock_resp

        results = self.scraper.query_stock("2330", dates=["20260226"])
        assert len(results) == 1
        assert results[0]["stock_code"] == "2330"
        assert results[0]["date"] == "20260226"
        assert abs(results[0]["ratio_400_above"] - 49.85) < 0.01

    def test_query_multiple_dates(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_RESULT_HTML
        self.scraper.session = MagicMock()
        self.scraper.session.post.return_value = mock_resp

        results = self.scraper.query_stock("2330")
        assert len(results) == 2  # 2 available dates

    def test_query_stock_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_NO_DATA_HTML
        self.scraper.session = MagicMock()
        self.scraper.session.post.return_value = mock_resp

        results = self.scraper.query_stock("9999")
        assert results == []


@pytest.mark.integration
class TestTDCCScraperIntegration:
    def test_init_and_query_tsmc(self):
        scraper = TDCCScraper()
        scraper.init_session()
        assert len(scraper.available_dates) > 40

        # Query single date for TSMC
        results = scraper.query_stock("2330", dates=[scraper.available_dates[0]])
        assert len(results) == 1
        assert results[0]["stock_code"] == "2330"
        assert results[0]["ratio_400_above"] > 80  # TSMC has high institutional holding
        assert results[0]["ratio_1000_above"] > 70
