#!/usr/bin/env python3
"""
Trend-Following Strategy with Multi-Layer Protection
核心機制：
1. 趨勢跟隨 - 使用 20/50 日 SMA 判斷趨勢
2. 快速停損 - -5% 保護機制
3. 空頭偵測 - 20日跌破50日時快速出場（2022年保護）
4. 獲利了結 - +5% 時部分平倉
5. 部位管理 - 連續下跌時快速退出
"""

from typing import Optional
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '..')
from base_strategy import BaseStrategy


class TrendFollowingStrategy(BaseStrategy):
    """
    多層保護的趨勢跟隨策略

    進場邏輯:
    - SMA_20 > SMA_50（上升趨勢）
    - 價格接近 SMA_50（回調進場點）
    - SMA_50 向上傾斜（趨勢強度確認）

    出場邏輯（優先順序）:
    1. 快速停損 -5%（保護 2022 年大空頭）
    2. 趨勢反轉 - SMA_20 跌破 SMA_50（立即出場）
    3. 連續 5 天下跌（空頭訊號）
    4. 獲利了結 +5%
    5. 最大持倉天數
    """

    def __init__(
        self,
        symbol: str = "006208",
        sma_short: int = 20,
        sma_long: int = 50,
        stop_loss_pct: float = 0.05,
        profit_target_pct: float = 0.05,
        max_hold_days: int = 60,
        **kwargs
    ):
        # Initialize directly (without calling super)
        self.symbol = symbol
        self.sma_short = sma_short
        self.sma_long = sma_long
        self.stop_loss_pct = stop_loss_pct
        self.profit_target_pct = profit_target_pct
        self.max_hold_days = max_hold_days

        # Internal state
        self.state = self.get_extra_state_fields()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate SMA and other indicators"""
        # SMA (Simple Moving Average)
        df[f'SMA_{self.sma_short}'] = df['Close'].rolling(window=self.sma_short).mean()
        df[f'SMA_{self.sma_long}'] = df['Close'].rolling(window=self.sma_long).mean()

        return df

    def get_min_bars_required(self) -> int:
        """Minimum bars needed before first signal"""
        return max(self.sma_short, self.sma_long) + 10

    def check_entry_signal(self, row: pd.Series) -> Optional[str]:
        """
        Check if we should enter a long position

        Conditions:
        1. SMA_20 > SMA_50 (uptrend)
        2. Price near SMA_50 (pullback entry point)
        3. SMA_50 rising (trend strength confirmation)
        4. No bearish signal (no trend reversal detected)
        """

        sma_short = row.get(f'SMA_{self.sma_short}')
        sma_long = row.get(f'SMA_{self.sma_long}')
        close = row['Close']

        if pd.isna(sma_short) or pd.isna(sma_long):
            return None

        # Condition 1: Short MA > Long MA (uptrend)
        trend_up = sma_short > sma_long

        # Condition 2: Price near long MA (2% range)
        price_near_sma = close < sma_long * 1.02

        # Condition 3: Long MA is rising (trend strength)
        prev_sma_long = self.state.get('prev_sma_long')
        if prev_sma_long is None:
            sma_long_rising = True  # First signal, assume rising
        else:
            sma_long_rising = sma_long >= prev_sma_long

        # Condition 4: No trend reversal (short MA did not just cross below long MA)
        prev_sma_short = self.state.get('prev_sma_short')
        if prev_sma_short is None or prev_sma_long is None:
            ma_reversal = False
        else:
            ma_reversal = (prev_sma_short > prev_sma_long and sma_short < sma_long)
        not_reversing = not ma_reversal

        if trend_up and price_near_sma and sma_long_rising and not_reversing:
            return 'long'

        return None

    def check_exit_signal(self, row: pd.Series, entry_price: float, position: int) -> Optional[str]:
        """
        Check if we should exit the position

        Exit conditions (priority order):
        1. Stop loss -5% (protect 2022 crash)
        2. Trend reversal: SMA_20 crosses below SMA_50 (immediate exit)
        3. Excessive decline: 5 consecutive down days
        4. Profit target +5%
        5. Max hold days
        """

        if position == 0:
            return None

        close = row['Close']
        sma_short = row.get(f'SMA_{self.sma_short}')
        sma_long = row.get(f'SMA_{self.sma_long}')
        days_held = self.state.get('days_held', 0)

        if pd.isna(sma_short) or pd.isna(sma_long):
            return None

        # Priority 1: Fast stop loss -5% (2022 protection)
        stop_loss_price = entry_price * (1 - self.stop_loss_pct)
        if close <= stop_loss_price:
            return 'stop_loss'

        # Priority 2: Trend reversal - SMA_20 crosses below SMA_50
        prev_sma_short = self.state.get('prev_sma_short', sma_short)
        prev_sma_long = self.state.get('prev_sma_long', sma_long)
        if (prev_sma_short is not None and prev_sma_long is not None and
            prev_sma_short > prev_sma_long and sma_short < sma_long):
            return 'trend_reverse'

        # Priority 3: Excessive decline - 5 consecutive down days
        consecutive_down = self.state.get('consecutive_down_days', 0)
        if consecutive_down >= 5:
            return 'excessive_decline'

        # Priority 4: Profit target +5%
        profit_target_price = entry_price * (1 + self.profit_target_pct)
        if close >= profit_target_price:
            return 'profit_target'

        # Priority 5: Max hold days
        if days_held >= self.max_hold_days:
            return 'max_days'

        return None

    def get_extra_state_fields(self) -> dict:
        """Define extra state fields to track"""
        return {
            'prev_close': 0.0,
            'consecutive_down_days': 0,
            'days_held': 0,
            'prev_sma_short': None,
            'prev_sma_long': None,
        }

    def on_entry(self, row: pd.Series, direction: str):
        """Called when position is entered"""
        self.state['days_held'] = 0
        self.state['consecutive_down_days'] = 0

    def on_bar(self, row: pd.Series):
        """Called on every bar to update state"""
        close = row['Close']
        sma_short = row.get(f'SMA_{self.sma_short}')
        sma_long = row.get(f'SMA_{self.sma_long}')

        # Update consecutive down days
        prev_close = self.state.get('prev_close', close)
        if close < prev_close:
            self.state['consecutive_down_days'] = self.state.get('consecutive_down_days', 0) + 1
        else:
            self.state['consecutive_down_days'] = 0

        # Update days held
        self.state['days_held'] = self.state.get('days_held', 0) + 1

        # Save current state for next bar
        self.state['prev_close'] = close
        self.state['prev_sma_short'] = sma_short
        self.state['prev_sma_long'] = sma_long

    def on_exit(self, row: pd.Series):
        """Called when position is exited"""
        self.state['days_held'] = 0
        self.state['consecutive_down_days'] = 0
