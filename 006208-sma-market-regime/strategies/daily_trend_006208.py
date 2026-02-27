"""
Daily Trend Following Strategy for Taiwan 50 ETF (006208)
Implements 3-layer logic: Trend -> Momentum -> Reversal
"""

from typing import Optional, Dict, List, Any
import pandas as pd
import numpy as np
from datetime import datetime
from base_strategy import BaseStrategy


class DailyTrendStrategy(BaseStrategy):
    """
    日K趨勢跟蹤策略

    多層決策邏輯：
    1. 趨勢層：三重均線 (MA20 > MA60 > MA200)
    2. 動量層：MACD + RSI 確認力度
    3. 反轉層：反轉訊號偵測
    """

    def __init__(
        self,
        symbol: str = "006208",
        ma_short: int = 20,
        ma_medium: int = 60,
        ma_long: int = 200,
        rsi_period: int = 14,
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
        stop_loss_pct: float = 0.03,
        volume_threshold: float = 0.9,
        enable_time_filter: bool = True,
        **kwargs
    ):
        # 直接初始化以支持既有的測試
        # 均線參數
        self.symbol = symbol
        self.ma_short = ma_short
        self.ma_medium = ma_medium
        self.ma_long = ma_long

        # RSI 參數
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

        # 風險管理參數
        self.stop_loss_pct = stop_loss_pct

        # 濾網參數
        self.volume_threshold = volume_threshold
        self.enable_time_filter = enable_time_filter

        # 內部狀態（支持直接使用）
        self.position = None  # None: 空倉, 1: 持倉
        self.entry_price = None
        self.entry_time = None
        self.highest_price = None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算所有需要的技術指標

        Args:
            df: OHLCV 數據框 (必須包含 Open, High, Low, Close, Volume)

        Returns:
            附加指標的數據框
        """
        # 複製以避免 SettingWithCopyWarning
        df = df.copy()

        # 移動平均線
        df['MA20'] = df['Close'].rolling(window=self.ma_short).mean()
        df['MA60'] = df['Close'].rolling(window=self.ma_medium).mean()
        df['MA200'] = df['Close'].rolling(window=self.ma_long).mean()

        # RSI 計算
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / (loss + 1e-10)  # 避免除以零
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD 計算
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Histogram'] = df['MACD'] - df['MACD_Signal']

        # 波動率計算
        df['Daily_Range'] = (df['High'] - df['Low']) / df['Open']
        df['Volatility'] = df['Daily_Range'].rolling(window=20).mean()

        # 成交量均線
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()

        # 前期高低點（用於反轉檢測）
        df['High_252'] = df['High'].rolling(window=252).max()
        df['Low_252'] = df['Low'].rolling(window=252).min()

        return df

    def check_entry_signal(self, row: pd.Series) -> Optional[str]:
        """
        檢查進場信號（空倉狀態下調用）

        Args:
            row: 最新一根 K 棒資料（包含指標）

        Returns:
            "long": 做多
            None: 無訊號
        """
        # 檢查必要欄位
        if pd.isna(row.get('MA20')) or pd.isna(row.get('MA60')) or pd.isna(row.get('MA200')):
            return None

        # 層級 1：趨勢過濾 (Trend Filter)
        if not (row['Close'] > row['MA20'] > row['MA60'] > row['MA200']):
            return None

        # 檢查 MA20 向上傾斜（從狀態中取得前一期 MA20）
        prev_ma20 = self.state.get('prev_ma20') if hasattr(self, 'state') else None
        if prev_ma20 is not None and prev_ma20 >= row['MA20']:
            return None

        # 層級 2：動量確認 (Momentum Confirmation)
        if pd.isna(row.get('MACD')) or pd.isna(row.get('MACD_Signal')):
            return None

        if not (row['MACD'] > row['MACD_Signal'] and row['MACD'] > 0):
            return None

        # RSI 必須在合理範圍內
        if pd.isna(row.get('RSI')) or not (self.rsi_oversold < row['RSI'] < self.rsi_overbought):
            return None

        # 層級 3：濾網層 (Filter Layer)
        # 波動率濾網
        if pd.isna(row.get('Volatility')) or row.get('Volatility', 0) == 0:
            return None

        if row.get('Daily_Range', 0) < row.get('Volatility', 0) * 0.8:
            return None

        # 成交量濾網
        if pd.isna(row.get('Volume_MA20')) or row.get('Volume_MA20', 0) == 0:
            return None

        if row.get('Volume', 0) < row.get('Volume_MA20', 0) * self.volume_threshold:
            return None

        # 時間濾網（13:00-14:00 台灣午盤冷淡）
        if self.enable_time_filter:
            # 注意：此處假設 row 有 datetime index，實際回測時檢查
            # 本地策略執行時，由於 12:00 執行，跳過時間濾網
            pass

        return "long"

    def check_exit_signal(self, row: pd.Series, entry_price: float, position: int) -> Optional[str]:
        """
        檢查平倉信號（持倉狀態下調用）

        Args:
            row: 最新一根 K 棒資料
            entry_price: 進場價格
            position: 目前倉位 (1: 多, -1: 空)

        Returns:
            出場原因字串或 None（表示繼續持倉）
        """
        if entry_price is None or position == 0:
            return None

        current_price = row['Close']

        # 優先級 1：止損檢查
        stop_loss_price = entry_price * (1 - self.stop_loss_pct)
        if current_price <= stop_loss_price:
            return "stop"

        # 優先級 2：移動止損（追蹤最高點）
        highest_price = self.state.get('highest_price', current_price) if hasattr(self, 'state') else self.highest_price
        if highest_price is None:
            highest_price = current_price
        else:
            highest_price = max(highest_price, current_price)

        # 更新追蹤最高點
        if hasattr(self, 'state'):
            self.state.set('highest_price', highest_price)
        else:
            self.highest_price = highest_price

        trailing_stop = highest_price * (1 - 0.02)  # 2% 移動止損
        if current_price <= trailing_stop:
            return "trailing_stop"

        # 優先級 3：價格跌破 MA20
        if pd.notna(row.get('MA20')) and current_price < row['MA20']:
            return "ma20_break"

        # 優先級 4：RSI > 75 且開始下跌（過度買入反轉）
        if pd.notna(row.get('RSI')) and row.get('RSI', 0) > 75:
            prev_rsi = self.state.get('prev_rsi') if hasattr(self, 'state') else None
            if prev_rsi is not None and prev_rsi > row['RSI']:  # RSI 開始下跌
                return "rsi_reversal"

        # 優先級 5：MACD 轉為負值
        if pd.notna(row.get('MACD')) and pd.notna(row.get('MACD_Signal')):
            if row.get('MACD', 0) < 0 and row.get('MACD', 0) < row.get('MACD_Signal', 0):
                return "macd_negative"

        return None

    def get_extra_state_fields(self) -> Dict[str, Any]:
        """
        取得策略特定的額外狀態欄位

        Returns:
            額外狀態欄位字典
        """
        return {
            "prev_rsi": 50.0,
            "prev_macd": 0.0,
            "prev_macd_signal": 0.0,
            "highest_price": 0.0,
            "lowest_price": 0.0,
            "prev_ma20": 0.0,
        }

    def on_entry(self, row: pd.Series, direction: str) -> None:
        """
        進場時的回調

        Args:
            row: 進場時的 K 棒資料
            direction: 進場方向 ("long" 或 "short")
        """
        if hasattr(self, 'state'):
            self.state.set('highest_price', row['Close'])
            self.state.set('lowest_price', row['Close'])
        else:
            self.highest_price = row['Close']

    def on_bar(self, row: pd.Series) -> None:
        """
        每根 K 棒更新（持倉狀態下）

        Args:
            row: 當前 K 棒資料
        """
        # 更新前期指標值
        if hasattr(self, 'state'):
            self.state.set('prev_rsi', row.get('RSI', 50.0))
            self.state.set('prev_macd', row.get('MACD', 0.0))
            self.state.set('prev_macd_signal', row.get('MACD_Signal', 0.0))
            self.state.set('prev_ma20', row.get('MA20', 0.0))

            # 更新最高最低價格
            if self.state.get('position', 0) != 0:
                highest = self.state.get('highest_price', row['Close'])
                lowest = self.state.get('lowest_price', row['Close'])
                self.state.set('highest_price', max(highest, row['Close']))
                self.state.set('lowest_price', min(lowest, row['Close']))

    def get_min_bars_required(self) -> int:
        """
        取得策略所需的最小 K 棒數量

        Returns:
            最小 K 棒數量
        """
        return self.ma_long + 10

    def get_log_info(self, row: pd.Series) -> str:
        """
        取得日誌資訊

        Args:
            row: 當前 K 棒資料

        Returns:
            日誌字串
        """
        ma20 = row.get('MA20', 0)
        rsi = row.get('RSI', 0)
        macd = row.get('MACD', 0)
        return f"Close:{row['Close']:.0f} MA20:{ma20:.0f} RSI:{rsi:.1f} MACD:{macd:.4f}"


if __name__ == '__main__':
    # 簡單測試
    strategy = DailyTrendStrategy()
    print(f"Strategy initialized: {strategy.symbol}")
