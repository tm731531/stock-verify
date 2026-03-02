import pytest
from analysis.statistics import StatisticsReport


# 模擬 analyze_stock 回傳的結果
SAMPLE_ANALYSIS_RESULTS = [
    {
        "stock_code": "2330",
        "accumulation_count": 2,
        "surge_count": 1,
        "hit_rate": 50.0,
        "accumulations": [
            {"ratio_change": 3.5, "weeks": 4, "start_date": "20250307", "end_date": "20250404"},
            {"ratio_change": 2.0, "weeks": 3, "start_date": "20250601", "end_date": "20250622"},
        ],
        "surges": [
            {"max_gain_pct": 25.0, "max_drawdown_pct": 5.0, "days_to_peak": 15},
        ],
        "matches": [
            {
                "accumulation": {"ratio_change": 3.5, "weeks": 4},
                "surge": {"max_gain_pct": 25.0, "max_drawdown_pct": 5.0, "days_to_peak": 15},
            }
        ],
    },
    {
        "stock_code": "2317",
        "accumulation_count": 1,
        "surge_count": 1,
        "hit_rate": 100.0,
        "accumulations": [
            {"ratio_change": 5.0, "weeks": 5, "start_date": "20250401", "end_date": "20250506"},
        ],
        "surges": [
            {"max_gain_pct": 35.0, "max_drawdown_pct": 8.0, "days_to_peak": 20},
        ],
        "matches": [
            {
                "accumulation": {"ratio_change": 5.0, "weeks": 5},
                "surge": {"max_gain_pct": 35.0, "max_drawdown_pct": 8.0, "days_to_peak": 20},
            }
        ],
    },
    {
        "stock_code": "0050",
        "accumulation_count": 1,
        "surge_count": 0,
        "hit_rate": 0.0,
        "accumulations": [
            {"ratio_change": 1.5, "weeks": 3, "start_date": "20250501", "end_date": "20250522"},
        ],
        "surges": [],
        "matches": [],
    },
]


class TestStatisticsReport:
    def test_init(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        assert report is not None

    def test_overall_hit_rate(self):
        """吃貨→飆股整體成功率"""
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        # 4 個吃貨事件中 2 個成功 = 50%
        assert summary["overall_hit_rate"] == 50.0

    def test_total_accumulations(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        assert summary["total_accumulations"] == 4

    def test_total_surges(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        assert summary["total_surges"] == 2

    def test_avg_gain(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        # (25 + 35) / 2 = 30%
        assert summary["avg_gain_pct"] == 30.0

    def test_avg_days_to_peak(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        # (15 + 20) / 2 = 17.5
        assert summary["avg_days_to_peak"] == 17.5

    def test_avg_drawdown(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        # (5 + 8) / 2 = 6.5%
        assert summary["avg_drawdown_pct"] == 6.5

    def test_stocks_analyzed(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        assert summary["stocks_analyzed"] == 3

    def test_stocks_with_accumulation(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        assert summary["stocks_with_accumulation"] == 3

    def test_stocks_with_surge(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        summary = report.summary()
        assert summary["stocks_with_surge"] == 2

    def test_empty_results(self):
        report = StatisticsReport([])
        summary = report.summary()
        assert summary["overall_hit_rate"] == 0.0
        assert summary["total_accumulations"] == 0

    def test_top_gainers(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        top = report.top_gainers(n=5)
        assert len(top) == 2
        assert top[0]["stock_code"] == "2317"  # 35% > 25%
        assert top[0]["max_gain_pct"] == 35.0

    def test_format_text_report(self):
        report = StatisticsReport(SAMPLE_ANALYSIS_RESULTS)
        text = report.format_text()
        assert "成功率" in text or "hit_rate" in text.lower()
        assert "2330" in text or "2317" in text
