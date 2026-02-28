"""
006208 SMA 日線系統 - 設定管理器
================================
管理全域設定和策略設定
"""

import json
from pathlib import Path
from typing import Dict, Any


class ConfigManager:
    """設定管理器"""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 全域設定
        self.global_config_file = config_dir / "global.json"
        self.global_config = self._load_global_config()

        # 策略設定
        self.strategy_config_file = config_dir / "sma_strategy.json"
        self.strategy_config = self._load_strategy_config()

    def _load_global_config(self) -> Dict[str, Any]:
        """載入全域設定"""
        if self.global_config_file.exists():
            try:
                with open(self.global_config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        # 預設全域設定
        default = {
            "api_key": "YOUR_API_KEY",
            "secret_key": "YOUR_SECRET_KEY",
            "ca_path": "",
            "ca_passwd": "",
            "person_id": "",
            "simulation": True,
            "enable_ordering": False,
            "poll_interval": 5,
            "symbol": "0050",  # 006208 代碼
            "description": "台灣50 ETF (006208) 日線 SMA 市場制度系統"
        }

        self._save_config(self.global_config_file, default)
        return default

    def _load_strategy_config(self) -> Dict[str, Any]:
        """載入策略設定"""
        if self.strategy_config_file.exists():
            try:
                with open(self.strategy_config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        # 預設策略設定
        default = {
            "enabled": True,
            "strategy_name": "sma_market_regime",
            "description": "SMA 市場制度檢測 (20日 vs 50日)",

            # SMA 參數
            "sma_short": 20,
            "sma_long": 50,

            # ATR 波動率參數
            "atr_period": 14,
            "atr_ma_period": 20,
            "volatility_threshold_multiplier": 1.5,  # ATR > MA * 1.5
            "daily_drop_threshold": -0.03,  # 單日跌幅 > 3%

            # 進場/出場條件
            "entry_volatility_threshold": 1.3,  # 進場時波動率 < MA * 1.3
            "recent_entry_days": 5,  # 最近 5 天內不重複進場信號

            # 交易參數
            "max_trades_per_day": 1,  # 每日最多交易數
            "position_size": 1,  # 單筆交易數量
            "warmup_bars": 5,  # 熱身 K 棒數 (這天內足夠數據)

            # 部位管理
            "warning_action": "reduce",  # 警訊時的動作: reduce(減倉50%), hold(持有), exit(全部出場)
            "warning_reduction_pct": 0.5,  # 減倉百分比 (0.5 = 50%)

            # 通知
            "send_notifications": True,
            "notification_channels": ["log", "email"],  # log, email, slack
            "email_to": "your_email@example.com"
        }

        self._save_config(self.strategy_config_file, default)
        return default

    def _save_config(self, file_path: Path, config: Dict[str, Any]):
        """儲存設定"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def update_global_config(self, updates: Dict[str, Any]):
        """更新全域設定"""
        self.global_config.update(updates)
        self._save_config(self.global_config_file, self.global_config)

    def update_strategy_config(self, updates: Dict[str, Any]):
        """更新策略設定"""
        self.strategy_config.update(updates)
        self._save_config(self.strategy_config_file, self.strategy_config)

    def reload(self):
        """重新載入所有設定"""
        self.global_config = self._load_global_config()
        self.strategy_config = self._load_strategy_config()
