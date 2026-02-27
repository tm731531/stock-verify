"""
006208 SMA 市場制度策略
======================
3 條規則：波動率警訊、空頭確認、進場訊號
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple


class SMAMarketRegime:
    """SMA 市場制度檢測系統"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sma_short = config.get('sma_short', 50)
        self.sma_long = config.get('sma_long', 200)
        self.atr_period = config.get('atr_period', 14)
        self.atr_ma_period = config.get('atr_ma_period', 20)
        self.volatility_threshold = config.get('volatility_threshold_multiplier', 1.5)
        self.daily_drop_threshold = config.get('daily_drop_threshold', -0.03)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """計算技術指標"""
        df = df.copy()

        # SMA
        df['SMA_50'] = df['Close'].rolling(window=self.sma_short).mean()
        df['SMA_200'] = df['Close'].rolling(window=self.sma_long).mean()

        # ATR (平均真實範圍)
        df['TR'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift(1)),
                abs(df['Low'] - df['Close'].shift(1))
            )
        )
        df['ATR'] = df['TR'].rolling(window=self.atr_period).mean()
        df['ATR_MA'] = df['ATR'].rolling(window=self.atr_ma_period).mean()

        # 日收益率
        df['Daily_Return'] = df['Close'].pct_change()

        return df

    def detect_regime(self, last_row: pd.Series, prev_row: Optional[pd.Series] = None) -> Dict[str, Any]:
        """檢測市場制度和訊號"""
        result = {
            "regime": "unknown",  # bull, bear, transition
            "signal": None,  # warning, entry, hold
            "signal_type": None,
            "reason": "",
            "indicators": {
                "close": float(last_row.get('Close', 0)),
                "sma50": float(last_row.get('SMA_50', 0)),
                "sma200": float(last_row.get('SMA_200', 0)),
                "atr": float(last_row.get('ATR', 0)),
                "atr_ma": float(last_row.get('ATR_MA', 0)),
                "daily_return": float(last_row.get('Daily_Return', 0))
            }
        }

        # 檢查資料完整性
        if pd.isna(last_row.get('SMA_50')) or pd.isna(last_row.get('SMA_200')):
            return result

        sma50 = last_row['SMA_50']
        sma200 = last_row['SMA_200']
        atr = last_row.get('ATR', 0)
        atr_ma = last_row.get('ATR_MA', 0)
        daily_ret = last_row.get('Daily_Return', 0)

        # ===== 規則 1: 波動率爆炸警訊 =====
        if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
            if atr > atr_ma * self.volatility_threshold and daily_ret < self.daily_drop_threshold:
                result["signal"] = "warning"
                result["signal_type"] = "volatility_explosion"
                result["reason"] = f"波動爆炸(ATR {atr/atr_ma:.1f}x) + 跌幅{daily_ret*100:.1f}%"

        # ===== 規則 2: 趨勢確認 =====
        if sma50 < sma200:
            result["regime"] = "bear"
            if not result["signal"]:
                result["signal"] = "hold"
                result["reason"] = "空頭進行中: SMA50 < SMA200"
        else:
            result["regime"] = "bull"

        # ===== 規則 3: 進場機會 (空頭結束) =====
        if sma50 > sma200 and pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
            if atr <= atr_ma * self.config.get('entry_volatility_threshold', 1.3):
                if not result["signal"] or result["signal"] == "hold":
                    result["signal"] = "entry"
                    result["signal_type"] = "golden_cross"
                    result["reason"] = f"黃金交叉 + 波動正常(ATR {atr/atr_ma:.1f}x)"

        return result

    def get_market_status(self, df: pd.DataFrame) -> Dict[str, Any]:
        """取得市場狀態"""
        if df.empty or len(df) < self.sma_long:
            return {"status": "insufficient_data"}

        df = self.calculate_indicators(df)
        last_row = df.iloc[-1]

        regime_info = self.detect_regime(last_row)

        return {
            "status": "ok",
            "date": str(last_row.get('Date', '')),
            "close": float(last_row['Close']),
            "sma50": float(last_row['SMA_50']),
            "sma200": float(last_row['SMA_200']),
            "atr": float(last_row['ATR']),
            "atr_ma": float(last_row['ATR_MA']),
            "regime": regime_info["regime"],
            "signal": regime_info["signal"],
            "signal_type": regime_info["signal_type"],
            "reason": regime_info["reason"],
            "volatility_ratio": float(last_row['ATR'] / last_row['ATR_MA']) if last_row['ATR_MA'] > 0 else 0
        }


class StateManager:
    """狀態管理器"""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """載入狀態"""
        import json
        from pathlib import Path

        state_path = Path(self.state_file)
        if state_path.exists():
            try:
                with open(state_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        # 預設狀態
        return {
            "position": 0,  # 0: 無倉位, 1: 持多, -1: 持空
            "entry_price": 0,
            "entry_date": "",
            "trade_count": 0,
            "position_reduction": False,  # 是否已減倉
            "last_warning_date": "",
            "last_entry_date": ""
        }

    def save(self):
        """儲存狀態"""
        import json
        from pathlib import Path

        state_path = Path(self.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        """取得狀態值"""
        return self.state.get(key, default)

    def set(self, key: str, value: Any):
        """設定狀態值"""
        self.state[key] = value

    def reset_daily(self) -> bool:
        """每日重置計數"""
        from datetime import datetime

        today = datetime.now().strftime('%Y-%m-%d')
        last_date = self.state.get('last_reset_date', '')

        if last_date != today:
            self.state['trade_count'] = 0
            self.state['position_reduction'] = False
            self.state['last_reset_date'] = today
            self.save()
            return True

        return False
