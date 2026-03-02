"""Statistical analysis and reporting for whale accumulation study."""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class StatisticsReport:
    """Aggregate and report statistics from pattern detection results."""

    def __init__(self, analysis_results: List[Dict]):
        self.results = analysis_results

    def summary(self) -> Dict:
        """Calculate overall statistics."""
        total_acc = sum(r["accumulation_count"] for r in self.results)
        total_surge = sum(r["surge_count"] for r in self.results)
        all_matches = [m for r in self.results for m in r.get("matches", [])]

        gains = [m["surge"]["max_gain_pct"] for m in all_matches]
        days = [m["surge"]["days_to_peak"] for m in all_matches]
        drawdowns = [m["surge"]["max_drawdown_pct"] for m in all_matches]

        return {
            "stocks_analyzed": len(self.results),
            "stocks_with_accumulation": sum(
                1 for r in self.results if r["accumulation_count"] > 0
            ),
            "stocks_with_surge": sum(
                1 for r in self.results if r["surge_count"] > 0
            ),
            "total_accumulations": total_acc,
            "total_surges": total_surge,
            "overall_hit_rate": round(
                len(all_matches) / total_acc * 100 if total_acc else 0.0, 1
            ),
            "avg_gain_pct": round(sum(gains) / len(gains), 1) if gains else 0.0,
            "avg_days_to_peak": round(sum(days) / len(days), 1) if days else 0.0,
            "avg_drawdown_pct": round(
                sum(drawdowns) / len(drawdowns), 1
            ) if drawdowns else 0.0,
        }

    def top_gainers(self, n: int = 10) -> List[Dict]:
        """Return top N stocks by max gain after accumulation."""
        all_matches = []
        for r in self.results:
            for m in r.get("matches", []):
                all_matches.append(
                    {
                        "stock_code": r["stock_code"],
                        "max_gain_pct": m["surge"]["max_gain_pct"],
                        "days_to_peak": m["surge"]["days_to_peak"],
                        "ratio_change": m["accumulation"]["ratio_change"],
                        "accumulation_weeks": m["accumulation"]["weeks"],
                    }
                )
        return sorted(all_matches, key=lambda x: x["max_gain_pct"], reverse=True)[:n]

    def format_text(self) -> str:
        """Generate a readable text report."""
        s = self.summary()
        top = self.top_gainers(10)

        lines = [
            "=" * 60,
            "TDCC 大戶吃貨 → 飆股 實證分析報告",
            "=" * 60,
            "",
            f"分析股票數: {s['stocks_analyzed']}",
            f"出現吃貨樣態: {s['stocks_with_accumulation']} 檔",
            f"出現飆股現象: {s['stocks_with_surge']} 檔",
            "",
            f"總吃貨事件數: {s['total_accumulations']}",
            f"總飆股事件數: {s['total_surges']}",
            f"吃貨→飆股 成功率: {s['overall_hit_rate']}%",
            "",
            f"成功個案平均漲幅: {s['avg_gain_pct']}%",
            f"平均等待天數（至波段高點）: {s['avg_days_to_peak']} 天",
            f"平均最大回檔: {s['avg_drawdown_pct']}%",
            "",
        ]

        if top:
            lines.append("-" * 60)
            lines.append("Top 漲幅個案:")
            lines.append(f"{'代號':>6} | {'漲幅':>8} | {'等待天數':>8} | {'占比變化':>8} | {'吃貨週數':>8}")
            lines.append("-" * 60)
            for t in top:
                lines.append(
                    f"{t['stock_code']:>6} | "
                    f"{t['max_gain_pct']:>7.1f}% | "
                    f"{t['days_to_peak']:>7} 天 | "
                    f"{t['ratio_change']:>+7.1f}% | "
                    f"{t['accumulation_weeks']:>7} 週"
                )

        lines.append("=" * 60)
        return "\n".join(lines)
