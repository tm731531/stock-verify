"""Momentum Reversal Strategy for 006208"""

from typing import Optional
import pandas as pd
import numpy as np
from base_strategy import BaseStrategy


class MomentumReversalStrategy(BaseStrategy):
    """
    High Volatility Momentum Reversal Strategy - Long Only

    Entry: High volatility + RSI oversold + Price reversal up
    Exit: Volatility drops OR Stop loss OR Max hold days
    """

    def __init__(
        self,
        symbol: str = "006208",
        atr_period: int = 14,
        atr_mult_entry: float = 1.5,  # Entry when ATR > avg * 1.5
        atr_mult_exit: float = 0.8,   # Exit when ATR < avg * 0.8
        rsi_period: int = 14,
        rsi_oversold: int = 40,  # Enter when RSI < 40
        stop_loss_pct: float = 0.03,
        max_hold_days: int = 10,
        **kwargs
    ):
        # Initialize directly (without calling super) to support existing tests
        self.symbol = symbol
        self.atr_period = atr_period
        self.atr_mult_entry = atr_mult_entry
        self.atr_mult_exit = atr_mult_exit
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_days = max_hold_days

        # Internal state
        self.state = self.get_extra_state_fields()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ATR, RSI, and other indicators"""

        # ATR (Average True Range)
        df['TR'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift(1)),
                abs(df['Low'] - df['Close'].shift(1))
            )
        )
        df['ATR'] = df['TR'].rolling(window=self.atr_period).mean()
        df['ATR_MA'] = df['ATR'].rolling(window=self.atr_period).mean()

        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss.replace(0, 1e-10)
        df['RSI'] = 100 - (100 / (1 + rs))

        return df

    def get_min_bars_required(self) -> int:
        """Minimum bars needed before first signal"""
        return max(self.atr_period, self.rsi_period) + 10

    def check_entry_signal(self, row: pd.Series) -> Optional[str]:
        """
        Check if we should enter a long position

        Relaxed Entry conditions:
        1. Volatility present: ATR > avg_ATR * atr_mult_entry (relaxed from 1.5)
        2. Price action: Close > Open (today up)
        3. Optional: RSI not overbought (RSI < 75) - allows more entry opportunities
        """

        if pd.isna(row.get('ATR')) or pd.isna(row.get('RSI')):
            return None

        # Condition 1: ATR above average (relaxed threshold)
        atr_threshold = row.get('ATR_MA', row.get('ATR', 0)) * self.atr_mult_entry
        volatility_present = row['ATR'] > atr_threshold

        # Condition 2: Price going up today
        price_up = row['Close'] > row['Open']

        # Condition 3: RSI not in extreme overbought (allow wider range for uptrend)
        rsi_not_extreme = row['RSI'] < 75

        # Simplified logic: just need volatility + price up + RSI not extreme
        if volatility_present and price_up and rsi_not_extreme:
            return 'long'

        return None

    def check_exit_signal(self, row: pd.Series, entry_price: float, position: int) -> Optional[str]:
        """
        Check if we should exit the position

        Exit conditions (any one):
        1. Volatility drops: ATR < avg_ATR * 0.8
        2. Stop loss: Close <= entry_price * (1 - stop_loss_pct)
        3. Max hold days reached: position held > max_hold_days
        """

        if position == 0:
            return None

        # Get state
        days_held = self.state.get('days_held', 0)

        # Condition 1: Volatility drops
        atr_threshold = row.get('ATR_MA', row.get('ATR', 0)) * self.atr_mult_exit
        volatility_drops = row['ATR'] < atr_threshold

        if volatility_drops:
            return 'volatility_drop'

        # Condition 2: Stop loss
        stop_loss_price = entry_price * (1 - self.stop_loss_pct)
        if row['Close'] <= stop_loss_price:
            return 'stop_loss'

        # Condition 3: Max hold days
        if days_held >= self.max_hold_days:
            return 'max_days'

        return None

    def get_extra_state_fields(self) -> dict:
        """Define extra state fields to track"""
        return {
            'prev_close': 0.0,
            'prev_prev_close': 0.0,
            'days_held': 0,
        }

    def on_entry(self, row: pd.Series, direction: str):
        """Called when position is entered"""
        self.state['days_held'] = 0

    def on_bar(self, row: pd.Series):
        """Called on every bar to update state"""
        self.state['prev_prev_close'] = self.state.get('prev_close', row['Close'])
        self.state['prev_close'] = row['Close']
        self.state['days_held'] = self.state.get('days_held', 0) + 1

    def on_exit(self, row: pd.Series):
        """Called when position is exited"""
        self.state['days_held'] = 0
