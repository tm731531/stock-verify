import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from crawler.price_fetcher import PriceFetcher


def _mock_yf_download(tickers, start, end, **kwargs):
    """模擬 yfinance 回傳的日K線 DataFrame"""
    dates = pd.date_range(start=start, end=end, freq="B")[:5]  # 5 個交易日
    data = {
        "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
        "High": [102.0, 103.0, 104.0, 105.0, 106.0],
        "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
        "Close": [101.0, 102.0, 103.0, 104.0, 105.0],
        "Volume": [1000000, 1200000, 900000, 1100000, 1300000],
    }
    df = pd.DataFrame(data, index=dates[:len(data["Open"])])
    df.index.name = "Date"
    return df


class TestPriceFetcher:
    def test_init(self):
        fetcher = PriceFetcher()
        assert fetcher is not None

    @patch("crawler.price_fetcher.yf.download", side_effect=_mock_yf_download)
    def test_fetch_returns_dataframe(self, mock_dl):
        fetcher = PriceFetcher()
        df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    @patch("crawler.price_fetcher.yf.download", side_effect=_mock_yf_download)
    def test_fetch_has_required_columns(self, mock_dl):
        fetcher = PriceFetcher()
        df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        required = {"Open", "High", "Low", "Close", "Volume"}
        assert required.issubset(set(df.columns))

    @patch("crawler.price_fetcher.yf.download", side_effect=_mock_yf_download)
    def test_fetch_adds_tw_suffix(self, mock_dl):
        """台股代號需加 .TW 後綴給 yfinance"""
        fetcher = PriceFetcher()
        fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        mock_dl.assert_called_once()
        call_args = mock_dl.call_args
        assert call_args[0][0] == "2330.TW" or call_args[1].get("tickers") == "2330.TW"

    @patch("crawler.price_fetcher.yf.download", side_effect=_mock_yf_download)
    def test_fetch_adds_daily_change(self, mock_dl):
        """應計算每日漲跌幅"""
        fetcher = PriceFetcher()
        df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        assert "change_pct" in df.columns
        # 第二天: (102-101)/101 ≈ 0.99%
        assert abs(df["change_pct"].iloc[1] - 0.99) < 0.1

    @patch("crawler.price_fetcher.yf.download", return_value=pd.DataFrame())
    def test_fetch_empty_returns_empty(self, mock_dl):
        fetcher = PriceFetcher()
        df = fetcher.fetch("9999", start="2026-01-01", end="2026-02-28")
        assert len(df) == 0

    @patch("crawler.price_fetcher.yf.download", side_effect=Exception("API error"))
    def test_fetch_error_returns_empty(self, mock_dl):
        fetcher = PriceFetcher()
        df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        assert len(df) == 0


class TestPriceFetcherMerge:
    @patch("crawler.price_fetcher.yf.download", side_effect=_mock_yf_download)
    def test_merge_with_tdcc_data(self, mock_dl):
        """合併 TDCC 持股資料與日K線"""
        fetcher = PriceFetcher()
        price_df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")

        tdcc_records = [
            {"date": price_df.index[0].strftime("%Y%m%d"), "ratio_400_above": 89.0},
            {"date": price_df.index[2].strftime("%Y%m%d"), "ratio_400_above": 89.5},
        ]

        merged = fetcher.merge_with_tdcc(price_df, tdcc_records)
        assert "ratio_400_above" in merged.columns
        # 非 TDCC 日期的 ratio 應為 NaN
        assert merged["ratio_400_above"].notna().sum() == 2


@pytest.mark.integration
class TestPriceFetcherIntegration:
    def test_fetch_tsmc_real(self):
        fetcher = PriceFetcher()
        df = fetcher.fetch("2330", start="2026-01-01", end="2026-02-28")
        assert len(df) > 20  # 約 40 個交易日
        assert "change_pct" in df.columns
        assert df["Close"].iloc[-1] > 0
