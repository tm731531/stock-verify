#!/usr/bin/env python3
"""
Simple SMA Golden Cross Strategy with Stop Loss
簡單 SMA 黃金交叉策略 - 20日上穿50日進場，下穿出場，加入停損保護
"""

from typing import Optional
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '..')
from base_strategy import BaseStrategy


class SMAcrossoverStrategy(BaseStrategy):
    """
    SMA Golden/Death Cross Strategy

    進場邏輯:
    - 20日 SMA 上穿 50日 SMA（黃金交叉）

    出場邏輯（優先順序）:
    1. 快速停損 -5%（保護 2022 年大空頭）
    2. 20日 SMA 下穿 50日 SMA（死亡交叉 = 趨勢反轉）
    3. 最大持倉天數
    """

    def __init__(
        self,
        symbol: str = "006208",
        sma_short: int = 20,
        sma_long: int = 50,
        stop_loss_pct: float = 0.05,
        max_hold_days: int = 60,
        **kwargs
    ):
        # Initialize directly (without calling super)
        self.symbol = symbol
        self.sma_short = sma_short
        self.sma_long = sma_long
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_days = max_hold_days

        # Internal state
        self.state = self.get_extra_state_fields()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate SMA indicators"""
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

        Entry Signal: Golden Cross
        - 20日 SMA 上穿 50日 SMA
        - Previous bar: 20日 <= 50日
        - Current bar: 20日 > 50日
        """

        sma_short = row.get(f'SMA_{self.sma_short}')
        sma_long = row.get(f'SMA_{self.sma_long}')

        if pd.isna(sma_short) or pd.isna(sma_long):
            return None

        # Get previous bar's SMA values
        prev_sma_short = self.state.get('prev_sma_short')
        prev_sma_long = self.state.get('prev_sma_long')

        if prev_sma_short is None or prev_sma_long is None:
            return None  # Wait for second bar to detect crossover

        # Golden Cross: 20日 from <= 50日 to > 50日
        was_below_or_equal = prev_sma_short <= prev_sma_long
        now_above = sma_short > sma_long

        if was_below_or_equal and now_above:
            return 'long'

        return None

    def check_exit_signal(self, row: pd.Series, entry_price: float, position: int) -> Optional[str]:
        """
        Check if we should exit the position

        Exit conditions (priority order):
        1. Fast stop loss -5% (2022 protection)
        2. Death Cross: 20日 SMA crosses below 50日 SMA (trend reversal)
        3. Max hold days
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

        # Priority 2: Death Cross - 20日 SMA crosses below 50日 SMA
        prev_sma_short = self.state.get('prev_sma_short')
        prev_sma_long = self.state.get('prev_sma_long')

        if (prev_sma_short is not None and prev_sma_long is not None and
            prev_sma_short > prev_sma_long and sma_short < sma_long):
            return 'death_cross'

        # Priority 3: Max hold days
        if days_held >= self.max_hold_days:
            return 'max_days'

        return None

    def get_extra_state_fields(self) -> dict:
        """Define extra state fields to track"""
        return {
            'prev_close': 0.0,
            'days_held': 0,
            'prev_sma_short': None,
            'prev_sma_long': None,
        }

    def on_entry(self, row: pd.Series, direction: str):
        """Called when position is entered"""
        self.state['days_held'] = 0

    def on_bar(self, row: pd.Series):
        """Called on every bar to update state"""
        close = row['Close']
        sma_short = row.get(f'SMA_{self.sma_short}')
        sma_long = row.get(f'SMA_{self.sma_long}')

        # Update days held
        self.state['days_held'] = self.state.get('days_held', 0) + 1

        # Save current state for next bar
        self.state['prev_close'] = close
        self.state['prev_sma_short'] = sma_short
        self.state['prev_sma_long'] = sma_long

    def on_exit(self, row: pd.Series):
        """Called when position is exited"""
        self.state['days_held'] = 0
