"""
策略基礎類別
============
所有策略都必須繼承此類別並實作 calculate_indicators, check_entry_signal, check_exit_signal 方法
"""

import json
import pandas as pd
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


class StrategyState:
    """策略狀態管理器"""

    def __init__(self, state_file: Path, extra_fields: Dict[str, Any] = None):
        self.state_file = state_file
        self.extra_fields = extra_fields or {}
        self.state = self._load()

    def _load(self) -> Dict[str, Any]:
        """載入狀態"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return self._default_state()

    def _default_state(self) -> Dict[str, Any]:
        """預設狀態"""
        base = {
            "date": str(datetime.now().date()),
            "trade_count": 0,
            "last_bar_ts": "",
            "position": 0,           # 0: 無倉, 1: 多單, -1: 空單
            "entry_price": 0.0,
            "entry_time": "",
        }
        # 合併額外欄位
        base.update(self.extra_fields)
        return base

    def save(self):
        """儲存狀態"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            # 轉換 numpy 類型為 Python 原生類型
            state_serializable = self._make_serializable(self.state)
            json.dump(state_serializable, f, indent=2, ensure_ascii=False)

    def _make_serializable(self, obj):
        """遞迴轉換 numpy 類型為 JSON 可序列化的類型"""
        import numpy as np

        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj

    def reset_daily(self):
        """每日重置"""
        today = str(datetime.now().date())
        if self.state["date"] != today:
            self.state["date"] = today
            self.state["trade_count"] = 0
            self.state["last_bar_ts"] = ""
            self.save()
            return True
        return False

    def get(self, key: str, default=None):
        return self.state.get(key, default)

    def set(self, key: str, value):
        self.state[key] = value

    def __getitem__(self, key):
        return self.state[key]

    def __setitem__(self, key, value):
        self.state[key] = value


class BaseStrategy(ABC):
    """
    策略基礎類別

    所有策略都必須繼承此類別並實作以下方法：
    - calculate_indicators(df): 計算指標
    - check_entry_signal(row, state): 檢查進場訊號
    - check_exit_signal(row, state): 檢查出場訊號

    屬性：
    - name: 策略名稱
    - config: 策略參數設定
    - state: 策略狀態
    - enabled: 是否啟用
    """

    def __init__(self, name: str, config: Dict[str, Any], state_dir: Path):
        """
        初始化策略

        Args:
            name: 策略識別名稱 (用於檔案命名)
            config: 策略參數
            state_dir: 狀態檔案目錄
        """
        self.name = name
        self.config = config
        self.enabled = config.get('enabled', True)

        # 取得策略特定的額外狀態欄位
        extra_state_fields = self.get_extra_state_fields()

        # 狀態管理
        state_file = state_dir / f"{name}_state.json"
        self.state = StrategyState(state_file, extra_state_fields)

    def get_extra_state_fields(self) -> Dict[str, Any]:
        """
        取得策略特定的額外狀態欄位

        子類別可覆寫此方法來新增額外的狀態欄位
        """
        return {}

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算策略所需指標

        Args:
            df: 原始 K 棒資料 (columns: ts, Open, High, Low, Close, Volume)

        Returns:
            包含指標的 DataFrame
        """
        pass

    @abstractmethod
    def check_entry_signal(self, row: pd.Series) -> Optional[str]:
        """
        檢查進場訊號

        Args:
            row: 最新一根 K 棒資料 (包含指標)

        Returns:
            "long": 做多
            "short": 做空
            None: 無訊號
        """
        pass

    @abstractmethod
    def check_exit_signal(self, row: pd.Series, entry_price: float, position: int) -> Optional[str]:
        """
        檢查出場訊號

        Args:
            row: 最新一根 K 棒資料
            entry_price: 進場價格
            position: 目前倉位 (1: 多, -1: 空)

        Returns:
            出場原因字串 (如 "target", "stop", "signal") 或 None
        """
        pass

    def get_log_info(self, row: pd.Series) -> str:
        """
        取得日誌資訊

        子類別可覆寫此方法來自訂日誌輸出格式
        """
        return f"價:{row['Close']:.0f}"

    def on_entry(self, row: pd.Series, direction: str):
        """
        進場時的回調

        子類別可覆寫此方法來儲存進場時的額外資訊
        """
        pass

    def on_exit(self, row: pd.Series):
        """
        出場時的回調

        子類別可覆寫此方法來清理額外狀態
        """
        pass

    def get_min_bars_required(self) -> int:
        """
        取得策略所需的最小 K 棒數量

        子類別應覆寫此方法
        """
        return 30

    def get_warmup_bars(self) -> int:
        """
        取得每小時暖身 K 棒數量

        子類別可覆寫此方法
        """
        return self.config.get('warmup_bars', 5)

    def get_max_trades_per_day(self) -> int:
        """取得每日最大交易次數"""
        return self.config.get('max_trades_per_day', 5)

    def get_stop_points(self) -> float:
        """取得止損點數"""
        return self.config.get('stop_points', 15)

    def get_target_points(self) -> float:
        """取得止盈點數"""
        return self.config.get('target_points', 30)
