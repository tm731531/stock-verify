"""
006208 SMA 日線系統 - 主程式
============================
每日 12:30 執行一次的 Crontab 程式

使用方式：
    # 單次執行 (crontab)
    python main.py

    # 顯示狀態
    python main.py --status

    # 啟用/停用交易
    python main.py --enable / --disable

    # 重置狀態
    python main.py --reset

Crontab 設定:
    30 12 * * 1-5 cd /home/tom/shioaji-trading/working/sma_006208_daily_bot && python main.py

作者：Claude Code
日期：2026-02
"""

import os
import sys
import json
import logging
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

# 本地模組
from config_manager import ConfigManager
from trade_logger import TradeLogger
from sma_market_regime import SMAMarketRegime, StateManager

# =============================================================================
# 路徑設定
# =============================================================================

BASE_DIR = Path(__file__).parent
CONFIGS_DIR = BASE_DIR / "configs"
STATES_DIR = BASE_DIR / "states"
TRADES_DIR = BASE_DIR / "trades"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

# =============================================================================
# 日誌設定
# =============================================================================

LOG_FILE = LOGS_DIR / "sma_bot.log"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SMA006208Bot")

# =============================================================================
# 市場時間檢查 (台灣時間)
# =============================================================================

def is_market_trading_day() -> bool:
    """檢查今日是否為台灣股市交易日"""
    now = datetime.now()
    weekday = now.weekday()

    # 週六週日休市
    if weekday >= 5:
        return False

    # 可以添加國定假日檢查
    # 暫時簡化：只檢查工作日

    return True


def is_trading_time() -> bool:
    """檢查現在是否為交易時段 (台灣時間)"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 股票市場交易時間: 09:00 - 13:30
    # 我們設定為 12:30 執行，已接近收盤
    time_val = hour * 60 + minute

    # 12:30 前後 (11:30 - 14:00)
    start_time = 11 * 60 + 30  # 11:30
    end_time = 14 * 60  # 14:00

    return start_time <= time_val <= end_time

# =============================================================================
# 資料載入
# =============================================================================

def fetch_data_from_api(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """從 API 取得資料 (如果配置支援)"""
    try:
        import shioaji as sj
    except ImportError:
        logger.warning("shioaji 未安裝，跳過 API 資料取得")
        return None

    try:
        simulation = config.get('simulation', True)
        api = sj.Shioaji(simulation=simulation)

        # 登入
        api_key = config.get('api_key')
        secret_key = config.get('secret_key')

        if api_key == "YOUR_API_KEY":
            logger.warning("API_KEY 未設定，使用 CSV 資料")
            return None

        api.login(api_key=api_key, secret_key=secret_key)

        # 取得 006208 資料
        symbol = config.get('symbol', '0050')
        contract = getattr(api.Contracts.Stocks, symbol)

        # 取得今日 K 棒
        today_str = datetime.now().strftime('%Y-%m-%d')
        df = api.kbars(contract, start=today_str, end=today_str)

        if df is not None and not df.empty:
            api.logout()
            return pd.DataFrame({**df})

        api.logout()
        return None

    except Exception as e:
        logger.error(f"API 取得資料失敗: {e}")
        return None


def fetch_data_from_csv(csv_path: Path) -> Optional[pd.DataFrame]:
    """從 CSV 檔案取得資料"""
    try:
        df = pd.read_csv(csv_path, index_col='Date', parse_dates=True)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

        # 返回最後 250 天資料 (足夠 SMA 計算)
        return df.tail(250)

    except Exception as e:
        logger.error(f"CSV 讀取失敗: {e}")
        return None


def get_latest_data(config: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """取得最新資料"""
    # 優先嘗試 API
    df = fetch_data_from_api(config)
    if df is not None and not df.empty:
        return df

    # 回退到 CSV
    csv_path = DATA_DIR / "006208_historical.csv"
    if csv_path.exists():
        logger.info("使用 CSV 資料")
        return fetch_data_from_csv(csv_path)

    logger.error("無法取得資料")
    return None

# =============================================================================
# SMA 機器人
# =============================================================================

class SMA006208Bot:
    """SMA 006208 日線機器人"""

    def __init__(self):
        # 設定管理
        self.config_manager = ConfigManager(CONFIGS_DIR)
        self.global_config = self.config_manager.global_config
        self.strategy_config = self.config_manager.strategy_config

        # 交易紀錄
        self.trade_logger = TradeLogger(TRADES_DIR, LOGS_DIR)

        # 策略
        self.strategy = SMAMarketRegime(self.strategy_config)

        # 狀態管理
        state_file = STATES_DIR / "sma_bot_state.json"
        self.state = StateManager(str(state_file))

    def run_once(self):
        """執行一次檢查和交易"""
        logger.info("=" * 70)
        logger.info("SMA 006208 日線系統 - 開始執行")
        logger.info(f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)

        # 取得資料
        df = get_latest_data(self.global_config)
        if df is None or df.empty:
            logger.error("無法取得市場資料")
            return

        # 重置日計數
        reset = self.state.reset_daily()
        if reset:
            logger.info("日期變更，已重置每日計數")

        # 計算指標
        df_with_indicators = self.strategy.calculate_indicators(df.copy())
        market_status = self.strategy.get_market_status(df)

        if market_status.get('status') != 'ok':
            logger.warning(f"市場狀態: {market_status['status']}")
            return

        logger.info(f"市場訊號: {market_status['regime'].upper()}")
        logger.info(f"  價格: ${market_status['close']:.2f}")
        logger.info(f"  SMA50: ${market_status['sma50']:.2f}")
        logger.info(f"  SMA200: ${market_status['sma200']:.2f}")
        logger.info(f"  波動率: {market_status['volatility_ratio']:.2f}x")

        # 記錄訊號
        self.trade_logger.log_signal(
            signal_type=market_status['regime'],
            price=market_status['close'],
            sma50=market_status['sma50'],
            sma200=market_status['sma200'],
            details=market_status
        )

        # ===== 狀態管理和交易邏輯 =====
        position = self.state.get('position', 0)
        entry_price = self.state.get('entry_price', 0)

        logger.info(f"目前倉位: {['無倉位', '持多', '持空'][position + 1]}")

        # 處理警訊信號 (無論有無倉位)
        if market_status['signal'] == 'warning':
            logger.warning(f"⚠️ 空頭警訊: {market_status['reason']}")

            self.trade_logger.log_warning(
                price=market_status['close'],
                atr=market_status['atr'],
                atr_ma=market_status['atr_ma'],
                daily_ret=market_status.get('daily_return', 0),
                action=self.strategy_config.get('warning_action', 'reduce')
            )

            # 如果已持倉且未減倉，執行減倉
            if position > 0 and not self.state.get('position_reduction', False):
                logger.info("執行減倉 50% 保護資本")
                self.state.set('position_reduction', True)
                self.state.save()
                self.trade_logger.log_exit(
                    exit_price=market_status['close'],
                    entry_price=entry_price,
                    exit_reason="警訊減倉 (50%)",
                    position_size=1,
                    entry_type="long"
                )

        # 處理出場信號 (如果持倉)
        elif position > 0 and market_status['signal'] != 'entry':
            logger.info(f"出場訊號: {market_status['reason']}")

            self.trade_logger.log_exit(
                exit_price=market_status['close'],
                entry_price=entry_price,
                exit_reason=market_status['reason'],
                position_size=1,
                entry_type="long"
            )

            self.state.set('position', 0)
            self.state.set('entry_price', 0)
            self.state.set('entry_date', '')
            self.state.save()

        # 處理進場信號 (如果空手)
        elif position == 0 and market_status['signal'] == 'entry':
            max_trades = self.strategy_config.get('max_trades_per_day', 1)
            trade_count = self.state.get('trade_count', 0)

            if trade_count < max_trades:
                logger.info(f"🚀 進場訊號: {market_status['reason']}")

                self.trade_logger.log_entry(
                    entry_price=market_status['close'],
                    entry_type="long",
                    signal_reason=market_status['reason'],
                    position_size=1
                )

                self.state.set('position', 1)
                self.state.set('entry_price', market_status['close'])
                self.state.set('entry_date', datetime.now().strftime('%Y-%m-%d'))
                self.state.set('trade_count', trade_count + 1)
                self.state.set('position_reduction', False)
                self.state.save()

                logger.info(f"進場成功: 多方 @ ${market_status['close']:.2f}")
            else:
                logger.info(f"今日已達交易上限 ({trade_count}/{max_trades})")

        # 印出摘要
        self.trade_logger.print_summary()
        logger.info("=" * 70 + "\n")

# =============================================================================
# 狀態顯示
# =============================================================================

def print_status():
    """印出系統狀態"""
    config_manager = ConfigManager(CONFIGS_DIR)
    state_file = STATES_DIR / "sma_bot_state.json"
    state_manager = StateManager(str(state_file))

    print("\n" + "=" * 70)
    print("SMA 006208 日線系統 - 狀態")
    print("=" * 70)

    print("\n[全域設定]")
    print(f"  商品: {config_manager.global_config.get('symbol')}")
    print(f"  交易開關: {'啟用' if config_manager.global_config.get('enable_ordering') else '停用 (模擬模式)'}")
    print(f"  模擬模式: {'是' if config_manager.global_config.get('simulation') else '否'}")

    print("\n[策略設定]")
    print(f"  SMA短期: {config_manager.strategy_config.get('sma_short')} 日")
    print(f"  SMA長期: {config_manager.strategy_config.get('sma_long')} 日")
    print(f"  波動率閾值: {config_manager.strategy_config.get('volatility_threshold_multiplier')}x")

    print("\n[當前狀態]")
    position = state_manager.get('position', 0)
    pos_tag = {0: "無倉位", 1: "持多", -1: "持空"}.get(position, "?")
    print(f"  倉位: {pos_tag}")
    print(f"  進場價格: ${state_manager.get('entry_price', 0):.2f}")
    print(f"  進場日期: {state_manager.get('entry_date', '無')}")
    print(f"  今日交易數: {state_manager.get('trade_count', 0)}")

    print("\n" + "=" * 70 + "\n")

# =============================================================================
# 入口點
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SMA 006208 日線系統")
    parser.add_argument("--status", action="store_true", help="顯示系統狀態")
    parser.add_argument("--enable", action="store_true", help="啟用實際下單")
    parser.add_argument("--disable", action="store_true", help="停用下單 (模擬模式)")
    parser.add_argument("--reset", action="store_true", help="重置系統狀態")

    args = parser.parse_args()

    if args.status:
        print_status()
        return

    # 更新全域設定
    config_manager = ConfigManager(CONFIGS_DIR)

    if args.enable:
        config_manager.update_global_config({'enable_ordering': True})
        print("✓ 實際下單模式已啟用")
        return

    if args.disable:
        config_manager.update_global_config({'enable_ordering': False})
        print("✓ 模擬模式已啟用")
        return

    if args.reset:
        state_file = STATES_DIR / "sma_bot_state.json"
        if state_file.exists():
            state_file.unlink()
            print("✓ 系統狀態已重置")
        return

    # 檢查交易時間
    if not is_market_trading_day():
        logger.info("非交易日，跳過執行")
        return

    if not is_trading_time():
        logger.info("非交易時間，跳過執行")
        logger.info(f"目前時間: {datetime.now().strftime('%H:%M:%S')} (應為 11:30-14:00)")
        return

    # 執行
    bot = SMA006208Bot()
    bot.run_once()


if __name__ == "__main__":
    main()
