#!/usr/bin/env python3
"""
自適應多策略回測系統 (2019-2026 完整數據)

核心特性：
1. 實時市場環境檢測 (BULL/BEAR/RANGE/NEUTRAL)
   - 基於過去N天數據，不看未來數據
   - 判斷依據：價格位置、趨勢強度、成交量、下跌天數

2. 動態策略選擇
   - BULL環境 → SMA趨勢策略 (最適合上升趨勢)
   - BEAR環境 → 均值回歸策略 (防守型)
   - RANGE環境 → 高低突破策略 (捕捉區間震盪)
   - NEUTRAL環境 → 空倉或極小倉位

3. 完整的回測流程
   - 每日進行環境判斷→選擇策略→執行交易
   - 考慮換倉成本
   - 記錄每筆交易的環境和策略信息

4. 詳細的報告和對比分析
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class MarketEnvironmentDetector:
    """市場環境檢測器 - 基於過去N天數據判斷當前環境"""

    @staticmethod
    def detect_environment(df, current_idx):
        """
        基於past_data判斷當前環境，返回 'BULL' / 'BEAR' / 'RANGE' / 'NEUTRAL'

        Args:
            df: 完整數據框
            current_idx: 當前索引 (int)

        Returns:
            環境標籤 (str)
        """
        # 只用過去的數據
        if current_idx < 50:
            return 'NEUTRAL'  # 數據不足時保守

        past = df.iloc[:current_idx]

        # 信號 1: 價格位置相對於移動平均
        close = past['Close'].iloc[-1]
        sma50 = past['Close'].rolling(50).mean().iloc[-1]
        sma200 = past['Close'].rolling(200).mean().iloc[-1]

        # 信號 2: 趨勢強度 (30日內最高-最低)
        high_30 = past['High'].iloc[-30:].max()
        low_30 = past['Low'].iloc[-30:].min()
        trend_strength = (high_30 - low_30) / low_30

        # 信號 3: 成交量強度
        vol_recent = past['Volume'].iloc[-20:].mean()
        vol_hist = past['Volume'].iloc[-250:].mean()
        vol_ratio = vol_recent / vol_hist if vol_hist > 0 else 1.0

        # 信號 4: 近期下跌天數
        recent_returns = past['Close'].pct_change().iloc[-5:]
        down_days = (recent_returns < 0).sum()

        # 信號 5: 近期上升趨勢
        momentum_20 = (past['Close'].iloc[-1] - past['Close'].iloc[-20]) / past['Close'].iloc[-20]

        # 決策邏輯
        if close > sma50 and close > sma200 and trend_strength > 0.05 and momentum_20 > 0.02:
            return 'BULL'  # 牛市：價格在均線上方，趨勢向上

        elif close < sma50 and down_days >= 3:
            return 'BEAR'  # 空頭：價格在均線下方，連續下跌

        elif trend_strength < 0.02:
            return 'RANGE'  # 震盪：波動小

        else:
            return 'NEUTRAL'  # 不確定


class AdaptiveIndicatorLibrary:
    """自適應指標庫 - 只計算所需指標"""

    @staticmethod
    def add_indicators(df):
        """計算必需的技術指標"""
        df = df.copy()

        # ===== 移動平均 =====
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['SMA50'] = df['Close'].rolling(50).mean()
        df['SMA200'] = df['Close'].rolling(200).mean()

        # ===== 布林帶 (均值回歸用) =====
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Up'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Low'] = df['BB_Mid'] - 2 * df['BB_Std']

        # ===== RSI (反轉判斷) =====
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # ===== ATR (波動率) =====
        df['TR'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift()),
                abs(df['Low'] - df['Close'].shift())
            )
        )
        df['ATR'] = df['TR'].rolling(14).mean()

        # ===== 高低點 (突破用) =====
        df['High20'] = df['High'].rolling(20).max()
        df['Low20'] = df['Low'].rolling(20).min()

        # ===== 日收益率 =====
        df['Daily_Return'] = df['Close'].pct_change()

        return df


class AdaptiveStrategyEngine:
    """自適應策略引擎 - 根據環境選擇合適的策略"""

    @staticmethod
    def get_sma_trend_signal(df, current_idx):
        """
        SMA趨勢策略 - 最適合BULL環境
        黃金叉(買入) / 死亡叉(賣出)
        """
        if current_idx < 50:
            return 0

        # 確保數據有效
        if pd.isna(df['SMA20'].iloc[current_idx]) or pd.isna(df['SMA50'].iloc[current_idx]):
            return 0

        current = df.iloc[current_idx]
        previous = df.iloc[current_idx - 1]

        # 黃金叉
        if (current['SMA20'] > current['SMA50'] and
            previous['SMA20'] <= previous['SMA50']):
            return 1

        # 死亡叉
        if (current['SMA20'] < current['SMA50'] and
            previous['SMA20'] >= previous['SMA50']):
            return -1

        return 0

    @staticmethod
    def get_mean_reversion_signal(df, current_idx):
        """
        均值回歸策略 - 最適合BEAR環境
        下軌+超賣(買入) / 上軌+超買(賣出)
        """
        if current_idx < 50:
            return 0

        if (pd.isna(df['BB_Low'].iloc[current_idx]) or
            pd.isna(df['BB_Up'].iloc[current_idx]) or
            pd.isna(df['RSI'].iloc[current_idx])):
            return 0

        current = df.iloc[current_idx]

        # 買入: 下軌 + 超賣
        if current['Close'] < current['BB_Low'] and current['RSI'] < 30:
            return 1

        # 賣出: 上軌 + 超買
        if current['Close'] > current['BB_Up'] or current['RSI'] > 70:
            return -1

        return 0

    @staticmethod
    def get_breakout_signal(df, current_idx):
        """
        高低突破策略 - 最適合RANGE環境
        突破20日高點(買入) / 突破20日低點(賣出)
        """
        if current_idx < 20:
            return 0

        if (pd.isna(df['High20'].iloc[current_idx]) or
            pd.isna(df['Low20'].iloc[current_idx])):
            return 0

        current = df.iloc[current_idx]
        previous = df.iloc[current_idx - 1]

        # 突破高點
        if (current['Close'] > previous['High20'] and
            current['Close'] > current['High20']):
            return 1

        # 突破低點
        if (current['Close'] < previous['Low20'] and
            current['Close'] < current['Low20']):
            return -1

        return 0

    @staticmethod
    def get_signal(df, current_idx, environment):
        """根據環境選擇策略並返回信號"""

        if environment == 'BULL':
            return AdaptiveStrategyEngine.get_sma_trend_signal(df, current_idx), 'SMA趨勢'

        elif environment == 'BEAR':
            return AdaptiveStrategyEngine.get_mean_reversion_signal(df, current_idx), '均值回歸'

        elif environment == 'RANGE':
            return AdaptiveStrategyEngine.get_breakout_signal(df, current_idx), '高低突破'

        else:  # NEUTRAL
            return 0, '空倉'


class RolloverManager:
    """換倉成本管理"""

    @staticmethod
    def get_rollover_dates(df):
        """計算所有換倉日期 (每月第三週水曜日)"""
        rollover_dates = []
        df_copy = df.copy()
        if isinstance(df_copy['Date'].iloc[0], str):
            df_copy['Date'] = pd.to_datetime(df_copy['Date'])

        current_year = df_copy['Date'].min().year
        end_year = df_copy['Date'].max().year
        max_date = df_copy['Date'].max()

        for year in range(current_year, end_year + 1):
            for month in range(1, 13):
                try:
                    month_start = pd.Timestamp(year=year, month=month, day=1)
                    for day in range(15, 22):
                        try:
                            date = pd.Timestamp(year=year, month=month, day=day)
                            if date.weekday() == 2:  # Wednesday
                                if month_start <= date <= max_date:
                                    rollover_dates.append(date)
                                break
                        except:
                            continue
                except:
                    pass

        return sorted(set(rollover_dates))

    @staticmethod
    def calculate_rollover_cost(rollover_dates):
        """計算換倉成本"""
        cost_per_roll = 6100  # ¥6,100 per rollover
        total_cost = len(rollover_dates) * cost_per_roll
        return {
            'num_rollovers': len(rollover_dates),
            'cost_per_roll': cost_per_roll,
            'total_cost': total_cost,
            'rollover_dates': rollover_dates
        }


class AdaptiveBacktester:
    """自適應回測引擎"""

    def __init__(self, df_daily, initial_capital=1000000, contract_size=200):
        self.df_daily = df_daily.copy()
        self.df_daily['Date'] = pd.to_datetime(self.df_daily['Date'])
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.rollover_cost_info = RolloverManager.calculate_rollover_cost(
            RolloverManager.get_rollover_dates(self.df_daily)
        )

    def backtest(self):
        """執行自適應回測"""
        df = self.df_daily.copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df = AdaptiveIndicatorLibrary.add_indicators(df)

        # 初始化記錄
        portfolio_values = [self.initial_capital]
        trades = []
        daily_logs = []

        position = 0
        entry_price = 0
        entry_date = None
        entry_environment = None
        entry_strategy = None

        # 回測迴圈：每天檢測環境→選擇策略→執行交易
        for current_idx in range(50, len(df)):
            current_price = df['Close'].iloc[current_idx]
            current_date = df['Date'].iloc[current_idx]

            # Step 1: 檢測環境
            environment = MarketEnvironmentDetector.detect_environment(df, current_idx)

            # Step 2: 根據環境選擇策略
            signal, strategy_name = AdaptiveStrategyEngine.get_signal(df, current_idx, environment)

            # Step 3: 執行交易邏輯
            if signal == 1 and position == 0:
                # 進場
                entry_price = current_price
                entry_date = current_date
                entry_environment = environment
                entry_strategy = strategy_name
                position = 1

                trades.append({
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'entry_environment': entry_environment,
                    'entry_strategy': entry_strategy,
                    'signal': 'BUY'
                })

            elif signal == -1 and position == 1:
                # 出場
                exit_price = current_price
                profit_pct = (exit_price - entry_price) / entry_price
                profit_points = (exit_price - entry_price) * self.contract_size

                days_held = (current_date - entry_date).days

                trades[-1].update({
                    'exit_date': current_date,
                    'exit_price': exit_price,
                    'profit_pct': profit_pct,
                    'profit_points': profit_points,
                    'days_held': days_held,
                    'exit_environment': environment,
                    'exit_strategy': strategy_name,
                    'signal': 'SELL'
                })
                position = 0

            # Step 4: 計算組合價值
            if position == 1:
                unrealized_pct = (current_price - entry_price) / entry_price
                current_value = self.initial_capital * (1 + unrealized_pct)
            else:
                current_value = self.initial_capital

            portfolio_values.append(current_value)

            # 記錄日誌
            daily_logs.append({
                'Date': current_date,
                'Close': current_price,
                'Environment': environment,
                'Strategy': strategy_name,
                'Signal': signal,
                'Position': position,
                'PortfolioValue': current_value
            })

        # 計算績效指標
        portfolio_values = np.array(portfolio_values)
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital

        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]

        if np.std(daily_returns) > 0:
            sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
        else:
            sharpe = 0

        # 計算最大回撤
        cummax = np.maximum.accumulate(portfolio_values)
        drawdown = (portfolio_values - cummax) / cummax
        max_drawdown = np.min(drawdown)

        # 統計交易數量
        num_trades = len([t for t in trades if 'exit_date' in t])

        results = {
            'total_return': total_return,
            'annual_return': total_return / 7,  # 7年數據
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'num_trades': num_trades,
            'portfolio_values': portfolio_values,
            'trades': trades,
            'daily_logs': daily_logs
        }

        return results


def load_data(filepath):
    """加載數據"""
    df = pd.read_csv(filepath)
    df['Date'] = pd.to_datetime(df['Date'])
    return df.sort_values('Date').reset_index(drop=True)


def main():
    """主函數"""

    # 加載數據
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv'
    logger.info(f"加載數據: {data_file}")
    df = load_data(data_file)
    logger.info(f"數據範圍: {df['Date'].min()} 到 {df['Date'].max()}, 共 {len(df)} 根 K線")

    # 執行自適應回測
    logger.info("\n開始自適應回測...")
    backtester = AdaptiveBacktester(df, initial_capital=1000000)
    results = backtester.backtest()

    # 保存結果
    output_dir = Path('/home/tom/TX_Quantitative_Trading/data')
    output_dir.mkdir(exist_ok=True)

    # 保存日誌為CSV
    daily_df = pd.DataFrame(results['daily_logs'])
    daily_df.to_csv(output_dir / 'adaptive_backtest_log.csv', index=False)
    logger.info(f"日誌已保存: {output_dir / 'adaptive_backtest_log.csv'}")

    # 保存詳細交易記錄
    trades_df = pd.DataFrame(results['trades'])
    trades_df.to_csv(output_dir / 'adaptive_trades.csv', index=False)
    logger.info(f"交易記錄已保存: {output_dir / 'adaptive_trades.csv'}")

    # 計算環境分佈
    env_dist = daily_df['Environment'].value_counts()
    env_pct = env_dist / len(daily_df) * 100

    logger.info("\n=== 環境分佈統計 ===")
    for env in ['BULL', 'BEAR', 'RANGE', 'NEUTRAL']:
        if env in env_dist.index:
            logger.info(f"{env:8s}: {env_dist[env]:4d} 天 ({env_pct[env]:5.1f}%)")

    # 計算各環境下的策略表現
    bull_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'BULL']
    bear_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'BEAR']
    range_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'RANGE']

    logger.info("\n=== 各環境下的策略表現 ===")

    if bull_trades:
        bull_returns = [t['profit_pct'] for t in bull_trades]
        logger.info(f"BULL環境 (SMA趨勢):")
        logger.info(f"  交易次數: {len(bull_trades)}")
        logger.info(f"  平均收益: {np.mean(bull_returns)*100:.2f}%")
        logger.info(f"  勝率: {sum(1 for r in bull_returns if r > 0) / len(bull_returns) * 100:.1f}%")

    if bear_trades:
        bear_returns = [t['profit_pct'] for t in bear_trades]
        logger.info(f"BEAR環境 (均值回歸):")
        logger.info(f"  交易次數: {len(bear_trades)}")
        logger.info(f"  平均收益: {np.mean(bear_returns)*100:.2f}%")
        logger.info(f"  勝率: {sum(1 for r in bear_returns if r > 0) / len(bear_returns) * 100:.1f}%")

    if range_trades:
        range_returns = [t['profit_pct'] for t in range_trades]
        logger.info(f"RANGE環境 (高低突破):")
        logger.info(f"  交易次數: {len(range_trades)}")
        logger.info(f"  平均收益: {np.mean(range_returns)*100:.2f}%")
        logger.info(f"  勝率: {sum(1 for r in range_returns if r > 0) / len(range_returns) * 100:.1f}%")

    # 回測結果總結
    logger.info("\n=== 自適應回測結果 ===")
    logger.info(f"總收益: {results['total_return']*100:.2f}%")
    logger.info(f"年化收益: {results['annual_return']*100:.2f}%")
    logger.info(f"Sharpe比率: {results['sharpe_ratio']:.4f}")
    logger.info(f"最大回撤: {results['max_drawdown']*100:.2f}%")
    logger.info(f"完成交易: {results['num_trades']} 次")

    return results


if __name__ == '__main__':
    main()
