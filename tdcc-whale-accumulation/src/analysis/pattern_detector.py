"""Detect whale accumulation patterns and subsequent price surges."""

import logging
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class PatternDetector:
    """Identify 'accumulation' and 'surge' patterns from TDCC + price data."""

    def __init__(
        self,
        min_accumulation_weeks: int = 3,
        min_surge_pct: float = 10.0,
    ):
        self.min_accumulation_weeks = min_accumulation_weeks
        self.min_surge_pct = min_surge_pct

    def detect_accumulation(self, tdcc_df: pd.DataFrame) -> List[Dict]:
        """
        Detect periods where ratio_400_above rises consecutively.

        Args:
            tdcc_df: DataFrame with 'date' and 'ratio_400_above' columns.

        Returns:
            List of accumulation signals with start/end dates and magnitude.
        """
        if tdcc_df.empty or len(tdcc_df) < self.min_accumulation_weeks:
            return []

        ratios = tdcc_df["ratio_400_above"].values
        dates = tdcc_df["date"].values
        signals = []

        streak_start = 0
        for i in range(1, len(ratios)):
            if ratios[i] > ratios[i - 1]:
                # 繼續上升
                continue
            else:
                # 上升結束，檢查是否達到門檻
                # streak_len = 連續上升次數（轉換次數，非資料點數）
                streak_len = i - streak_start - 1
                if streak_len >= self.min_accumulation_weeks:
                    signals.append(
                        {
                            "type": "accumulation",
                            "start_date": str(dates[streak_start]),
                            "end_date": str(dates[i - 1]),
                            "start_ratio": float(ratios[streak_start]),
                            "end_ratio": float(ratios[i - 1]),
                            "ratio_change": round(
                                float(ratios[i - 1] - ratios[streak_start]), 2
                            ),
                            "weeks": streak_len,
                        }
                    )
                streak_start = i

        # 檢查結尾仍在上升的情況
        streak_len = len(ratios) - streak_start - 1
        if streak_len >= self.min_accumulation_weeks:
            # 確認最後一段確實是上升的
            is_rising = all(
                ratios[j] > ratios[j - 1]
                for j in range(streak_start + 1, len(ratios))
            )
            if is_rising:
                signals.append(
                    {
                        "type": "accumulation",
                        "start_date": str(dates[streak_start]),
                        "end_date": str(dates[-1]),
                        "start_ratio": float(ratios[streak_start]),
                        "end_ratio": float(ratios[-1]),
                        "ratio_change": round(
                            float(ratios[-1] - ratios[streak_start]), 2
                        ),
                        "weeks": streak_len,
                    }
                )

        return signals

    def detect_surge(
        self,
        price_df: pd.DataFrame,
        accumulation: Dict,
        lookforward_days: int = 60,
    ) -> Optional[Dict]:
        """
        Check if a price surge occurred after an accumulation period.

        Args:
            price_df: DataFrame with DatetimeIndex and 'Close' column.
            accumulation: Accumulation signal dict with 'end_date'.
            lookforward_days: How many trading days to look ahead.

        Returns:
            Surge dict or None if no significant surge detected.
        """
        if price_df.empty:
            return None

        end_date = pd.Timestamp(accumulation["end_date"])

        # 找吃貨結束後的價格序列
        future_prices = price_df[price_df.index >= end_date]
        if len(future_prices) < 2:
            return None

        future_prices = future_prices.head(lookforward_days)
        base_price = future_prices["Close"].iloc[0]

        if base_price <= 0:
            return None

        # 計算最大漲幅
        max_price = future_prices["Close"].max()
        max_gain_pct = (max_price - base_price) / base_price * 100

        if max_gain_pct < self.min_surge_pct:
            return None

        # 計算最大回檔（從最高點到之後的最低點）
        max_idx = future_prices["Close"].idxmax()
        after_peak = future_prices[future_prices.index >= max_idx]
        if len(after_peak) > 1:
            min_after_peak = after_peak["Close"].min()
            max_drawdown_pct = (max_price - min_after_peak) / max_price * 100
        else:
            max_drawdown_pct = 0.0

        return {
            "type": "surge",
            "base_price": float(base_price),
            "max_price": float(max_price),
            "max_gain_pct": round(max_gain_pct, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "peak_date": max_idx.strftime("%Y%m%d"),
            "days_to_peak": (max_idx - end_date).days,
        }

    def analyze_stock(
        self,
        stock_code: str,
        tdcc_df: pd.DataFrame,
        price_df: pd.DataFrame,
    ) -> Dict:
        """
        Full analysis pipeline for a single stock.

        Returns:
            Dict with stock_code, accumulations, surges, and matches.
        """
        accumulations = self.detect_accumulation(tdcc_df)
        surges = []
        matches = []

        for acc in accumulations:
            surge = self.detect_surge(price_df, acc)
            if surge:
                surges.append(surge)
                matches.append({"accumulation": acc, "surge": surge})

        return {
            "stock_code": stock_code,
            "accumulations": accumulations,
            "surges": surges,
            "matches": matches,
            "accumulation_count": len(accumulations),
            "surge_count": len(surges),
            "hit_rate": (
                len(matches) / len(accumulations) * 100
                if accumulations
                else 0.0
            ),
        }
