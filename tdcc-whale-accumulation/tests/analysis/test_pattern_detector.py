import pytest
import pandas as pd
from analysis.pattern_detector import PatternDetector


def _make_tdcc_series(ratios, start_date="20250307"):
    """建立模擬 TDCC 持股占比時間序列"""
    dates = pd.date_range(start=start_date, periods=len(ratios), freq="7D")
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y%m%d") for d in dates],
            "ratio_400_above": ratios,
            "stock_code": "TEST",
        }
    )


def _make_price_series(prices, start_date="2025-03-07"):
    """建立模擬日K線"""
    dates = pd.date_range(start=start_date, periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "Close": prices,
            "Volume": [1000000] * len(prices),
        },
        index=dates,
    )


class TestDetectAccumulation:
    """測試「吃貨」樣態偵測"""

    def test_detects_rising_ratio(self):
        """連續 3 週以上占比上升 = 吃貨"""
        # 連續 5 週上升
        tdcc = _make_tdcc_series([40.0, 41.0, 42.5, 44.0, 46.0])
        detector = PatternDetector()
        signals = detector.detect_accumulation(tdcc)
        assert len(signals) > 0
        assert signals[0]["type"] == "accumulation"

    def test_no_signal_on_flat(self):
        """占比不變 = 無訊號"""
        tdcc = _make_tdcc_series([40.0, 40.0, 40.0, 40.0, 40.0])
        detector = PatternDetector()
        signals = detector.detect_accumulation(tdcc)
        assert len(signals) == 0

    def test_no_signal_on_declining(self):
        """占比下降 = 無訊號"""
        tdcc = _make_tdcc_series([46.0, 44.0, 42.0, 40.0, 38.0])
        detector = PatternDetector()
        signals = detector.detect_accumulation(tdcc)
        assert len(signals) == 0

    def test_min_consecutive_weeks(self):
        """需至少 min_weeks 週連續上升"""
        # 只有 2 週上升（不滿預設的 3 週）
        tdcc = _make_tdcc_series([40.0, 41.0, 42.0, 41.5, 40.0])
        detector = PatternDetector(min_accumulation_weeks=3)
        signals = detector.detect_accumulation(tdcc)
        assert len(signals) == 0

    def test_detects_accumulation_magnitude(self):
        """訊號應包含漲幅資訊"""
        tdcc = _make_tdcc_series([40.0, 42.0, 44.0, 46.0])
        detector = PatternDetector()
        signals = detector.detect_accumulation(tdcc)
        assert signals[0]["ratio_change"] == pytest.approx(6.0, abs=0.1)  # 46 - 40
        assert signals[0]["start_date"] is not None
        assert signals[0]["end_date"] is not None

    def test_multiple_accumulation_periods(self):
        """同一股票可能有多個吃貨期間"""
        # 吃貨 → 出貨 → 再吃貨
        tdcc = _make_tdcc_series([40, 42, 44, 46, 43, 40, 41, 43, 45, 47])
        detector = PatternDetector()
        signals = detector.detect_accumulation(tdcc)
        assert len(signals) >= 2


class TestDetectSurge:
    """測試「飆股」現象偵測"""

    def test_detects_surge_after_accumulation(self):
        """吃貨後股價大漲 = 飆股"""
        price_df = _make_price_series(
            [100, 100, 101, 102, 105, 110, 115, 120, 125, 130]
        )
        accumulation = {
            "type": "accumulation",
            "end_date": price_df.index[2].strftime("%Y%m%d"),
        }
        detector = PatternDetector()
        surge = detector.detect_surge(price_df, accumulation, lookforward_days=30)
        assert surge is not None
        assert surge["max_gain_pct"] > 20  # 從 101 到 130 ≈ +28.7%

    def test_no_surge_on_flat_price(self):
        """吃貨後股價沒漲 = 不算飆股"""
        price_df = _make_price_series([100, 100, 101, 100, 101, 100, 101, 100])
        accumulation = {
            "type": "accumulation",
            "end_date": price_df.index[2].strftime("%Y%m%d"),
        }
        detector = PatternDetector()
        surge = detector.detect_surge(price_df, accumulation, lookforward_days=30)
        assert surge is None

    def test_surge_with_min_gain(self):
        """可設定最低漲幅門檻"""
        price_df = _make_price_series([100, 100, 101, 105, 108, 110])
        accumulation = {
            "type": "accumulation",
            "end_date": price_df.index[2].strftime("%Y%m%d"),
        }
        detector = PatternDetector(min_surge_pct=15.0)
        surge = detector.detect_surge(price_df, accumulation, lookforward_days=30)
        assert surge is None  # 只漲 ~9%，低於 15% 門檻

    def test_surge_reports_max_drawdown(self):
        """飆股報告應包含最大回檔"""
        price_df = _make_price_series(
            [100, 100, 101, 110, 105, 115, 120, 130]
        )
        accumulation = {
            "type": "accumulation",
            "end_date": price_df.index[2].strftime("%Y%m%d"),
        }
        detector = PatternDetector(min_surge_pct=10.0)
        surge = detector.detect_surge(price_df, accumulation, lookforward_days=30)
        assert surge is not None
        assert "max_drawdown_pct" in surge


class TestAnalyzeStock:
    """測試完整的單股分析流程"""

    def test_analyze_returns_result(self):
        tdcc = _make_tdcc_series([40, 42, 44, 46, 47, 47.5, 48])
        price_df = _make_price_series(
            [100] * 5 + [105, 110, 115, 120, 125, 130, 135, 140] + [140] * 30,
            start_date="2025-03-07",
        )
        detector = PatternDetector()
        result = detector.analyze_stock("TEST", tdcc, price_df)
        assert result["stock_code"] == "TEST"
        assert "accumulations" in result
        assert "surges" in result

    def test_analyze_empty_data(self):
        detector = PatternDetector()
        tdcc = pd.DataFrame(columns=["date", "ratio_400_above", "stock_code"])
        price_df = pd.DataFrame()
        result = detector.analyze_stock("TEST", tdcc, price_df)
        assert result["accumulations"] == []
        assert result["surges"] == []
