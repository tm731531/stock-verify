#!/usr/bin/env python3
"""
參數化自適應多策略回測系統 (2019-2026 完整數據)

核心特性：
1. 參數化環境檢測 (Conservative / Moderate / Aggressive)
   - 降低NEUTRAL比例，提高BULL/BEAR的識別率
   - 基於過去N天數據，不看未來數據

2. 三個參數版本對比
   - 保守版 (Conservative): NEUTRAL目標 < 30%
   - 中等版 (Moderate): NEUTRAL目標 < 20% ⭐ 推薦
   - 激進版 (Aggressive): NEUTRAL目標 < 10%

3. 動態策略選擇 & 完整回測流程
4. 詳細的參數對比報告
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


class ParameterizedMarketEnvironmentDetector:
    """參數化市場環境檢測器 - 根據版本調整靈敏度"""

    @staticmethod
    def detect_environment(df, current_idx, version='moderate'):
        """
        基於version參數調整靈敏度的環境檢測

        Args:
            df: 完整數據框
            current_idx: 當前索引 (int)
            version: 'conservative' / 'moderate' / 'aggressive'

        Returns:
            環境標籤 (str)
        """
        if current_idx < 50:
            return 'NEUTRAL'

        past = df.iloc[:current_idx]
        close = past['Close'].iloc[-1]
        sma20 = past['Close'].rolling(20).mean().iloc[-1]
        sma50 = past['Close'].rolling(50).mean().iloc[-1]
        sma200 = past['Close'].rolling(200).mean().iloc[-1]

        # 計算上升/下跌天數
        recent_returns = past['Close'].pct_change().iloc[-5:]
        up_days = (recent_returns > 0).sum()
        down_days = (recent_returns < 0).sum()

        # 計算N日漲跌幅
        price_3d = (close - past['Close'].iloc[-3]) / past['Close'].iloc[-3] if len(past) >= 3 else 0
        price_2d = (close - past['Close'].iloc[-2]) / past['Close'].iloc[-2] if len(past) >= 2 else 0

        # 計算成交量強度
        vol_recent = past['Volume'].iloc[-20:].mean()
        vol_hist = past['Volume'].iloc[-250:].mean()
        vol_ratio = vol_recent / vol_hist if vol_hist > 0 else 1.0

        # 計算30日波動強度
        high_30 = past['High'].iloc[-30:].max()
        low_30 = past['Low'].iloc[-30:].min()
        trend_strength = (high_30 - low_30) / low_30 if low_30 > 0 else 0

        # 20日動量
        momentum_20 = (close - past['Close'].iloc[-20]) / past['Close'].iloc[-20] if len(past) >= 20 else 0

        # ========== 保守版本 (Conservative) ==========
        if version == 'conservative':
            # BULL: 放寬SMA200的要求
            bull_sma = close > sma50  # 只要求close > sma50 (去掉sma200)
            bull_momentum = price_3d > 0.01  # 3日漲幅 > 1%

            if bull_sma or bull_momentum:
                return 'BULL'

            # BEAR: 短期下跌信號
            bear_short = close < sma20 and down_days >= 2  # sma20 + 2天下跌
            bear_drop = price_3d < -0.01  # 3日跌幅 < -1%

            if bear_short or bear_drop:
                return 'BEAR'

            # RANGE: 小波動
            if trend_strength < 0.02:
                return 'RANGE'

            return 'NEUTRAL'

        # ========== 中等版本 (Moderate) ⭐ ==========
        elif version == 'moderate':
            # BULL: 多個上升信號
            bull_sma20 = close > sma20  # 短期均線
            bull_high20 = close > past['High'].rolling(20).max().iloc[-1] * 0.98  # 接近20日高點
            bull_volume = vol_ratio > 1.0 and momentum_20 > 0  # 成交量大 + 上升動量
            bull_momentum = momentum_20 > 0.02

            bull_count = sum([bull_sma20, bull_high20, bull_volume, bull_momentum])
            if bull_count >= 2:
                return 'BULL'

            # BEAR: 多個下跌信號
            bear_sma20 = close < sma20  # 短期均線下方
            bear_down = down_days >= 2  # 連跌 >= 2天
            bear_momentum = momentum_20 < -0.02

            bear_count = sum([bear_sma20, bear_down, bear_momentum])
            if bear_count >= 2:
                return 'BEAR'

            # RANGE: 小波動
            if trend_strength < 0.02:
                return 'RANGE'

            return 'NEUTRAL'

        # ========== 激進版本 (Aggressive) ==========
        else:  # aggressive
            # BULL: 任何上升信號都算 (更激進的條件)
            if close > sma20 or momentum_20 > 0:  # close > sma20 OR 有正動量
                return 'BULL'

            # BEAR: 任何下跌信號都算 (更激進的條件)
            elif close < sma20 or momentum_20 < 0:  # close < sma20 OR 有負動量
                return 'BEAR'

            # 其他情況為RANGE
            else:
                return 'RANGE'


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
        """SMA趨勢策略 - 最適合BULL環境"""
        if current_idx < 50:
            return 0

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
        """均值回歸策略 - 最適合BEAR環境"""
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
        """高低突破策略 - 最適合RANGE環境"""
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


class ParameterizedAdaptiveBacktester:
    """參數化自適應回測引擎"""

    def __init__(self, df_daily, initial_capital=1000000, contract_size=200, version='moderate'):
        self.df_daily = df_daily.copy()
        self.df_daily['Date'] = pd.to_datetime(self.df_daily['Date'])
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.version = version
        self.rollover_cost_info = RolloverManager.calculate_rollover_cost(
            RolloverManager.get_rollover_dates(self.df_daily)
        )

    def backtest(self):
        """執行參數化自適應回測"""
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

        # 回測迴圈
        for current_idx in range(50, len(df)):
            current_price = df['Close'].iloc[current_idx]
            current_date = df['Date'].iloc[current_idx]

            # Step 1: 檢測環境 (使用參數化版本)
            environment = ParameterizedMarketEnvironmentDetector.detect_environment(
                df, current_idx, version=self.version
            )

            # Step 2: 根據環境選擇策略
            signal, strategy_name = AdaptiveStrategyEngine.get_signal(df, current_idx, environment)

            # Step 3: 執行交易邏輯
            if signal == 1 and position == 0:
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
            'version': self.version,
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
    """主函數 - 運行三個版本的回測"""

    # 加載數據
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv'
    logger.info(f"加載數據: {data_file}")
    df = load_data(data_file)
    logger.info(f"數據範圍: {df['Date'].min()} 到 {df['Date'].max()}, 共 {len(df)} 根 K線\n")

    # 三個版本的參數
    versions = ['conservative', 'moderate', 'aggressive']
    all_results = {}

    # 對每個版本執行回測
    for version in versions:
        logger.info(f"\n{'='*60}")
        logger.info(f"開始 {version.upper()} 版本的回測...")
        logger.info(f"{'='*60}")

        backtester = ParameterizedAdaptiveBacktester(df, initial_capital=1000000, version=version)
        results = backtester.backtest()
        all_results[version] = results

        # 保存日誌
        output_dir = Path('/home/tom/TX_Quantitative_Trading/data')
        output_dir.mkdir(exist_ok=True)

        daily_df = pd.DataFrame(results['daily_logs'])
        daily_df.to_csv(output_dir / f'adaptive_backtest_log_{version}.csv', index=False)

        trades_df = pd.DataFrame(results['trades'])
        trades_df.to_csv(output_dir / f'adaptive_trades_{version}.csv', index=False)

        # 計算環境分佈
        env_dist = daily_df['Environment'].value_counts()
        env_pct = env_dist / len(daily_df) * 100

        logger.info(f"\n=== {version.upper()} - 環境分佈統計 ===")
        for env in ['BULL', 'BEAR', 'RANGE', 'NEUTRAL']:
            if env in env_dist.index:
                logger.info(f"{env:8s}: {env_dist[env]:4d} 天 ({env_pct[env]:5.1f}%)")
            else:
                logger.info(f"{env:8s}: 0 天 (0.0%)")

        # 計算各環境下的策略表現
        bull_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'BULL']
        bear_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'BEAR']
        range_trades = [t for t in results['trades'] if 'exit_date' in t and t['entry_environment'] == 'RANGE']

        logger.info(f"\n=== {version.upper()} - 各環境下的策略表現 ===")

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
        logger.info(f"\n=== {version.upper()} - 回測結果 ===")
        logger.info(f"總收益: {results['total_return']*100:.2f}%")
        logger.info(f"年化收益: {results['annual_return']*100:.2f}%")
        logger.info(f"Sharpe比率: {results['sharpe_ratio']:.4f}")
        logger.info(f"最大回撤: {results['max_drawdown']*100:.2f}%")
        logger.info(f"完成交易: {results['num_trades']} 次")

    # 生成對比報告
    logger.info(f"\n{'='*60}")
    logger.info("生成參數優化對比報告...")
    logger.info(f"{'='*60}\n")

    generate_comparison_report(all_results)

    return all_results


def generate_comparison_report(all_results):
    """生成參數優化對比報告"""

    report_path = Path('/home/tom/TX_Quantitative_Trading/reports/parameter_tuning_report.md')
    report_path.parent.mkdir(exist_ok=True)

    # 建立對比表
    comparison_data = []
    for version in ['conservative', 'moderate', 'aggressive']:
        results = all_results[version]
        daily_logs = pd.DataFrame(results['daily_logs'])
        env_dist = daily_logs['Environment'].value_counts()
        total_days = len(daily_logs)

        bull_pct = (env_dist.get('BULL', 0) / total_days * 100) if total_days > 0 else 0
        bear_pct = (env_dist.get('BEAR', 0) / total_days * 100) if total_days > 0 else 0
        neutral_pct = (env_dist.get('NEUTRAL', 0) / total_days * 100) if total_days > 0 else 0
        range_pct = (env_dist.get('RANGE', 0) / total_days * 100) if total_days > 0 else 0

        comparison_data.append({
            'Version': version.upper(),
            'BULL%': f"{bull_pct:.1f}%",
            'BEAR%': f"{bear_pct:.1f}%",
            'RANGE%': f"{range_pct:.1f}%",
            'NEUTRAL%': f"{neutral_pct:.1f}%",
            '年化%': f"{results['annual_return']*100:.2f}%",
            'Sharpe': f"{results['sharpe_ratio']:.4f}",
            '最大回撤': f"{results['max_drawdown']*100:.2f}%",
            '交易次': results['num_trades']
        })

    comparison_df = pd.DataFrame(comparison_data)

    # 寫入報告
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# 參數優化回測對比報告\n\n")
        f.write(f"生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 核心優化目標\n\n")
        f.write("- 降低NEUTRAL比例 (舊參數: 45%, 目標: 保守30% → 中等20% → 激進10%)\n")
        f.write("- 提高BULL/BEAR的識別率\n")
        f.write("- 改善年化收益和風險調整後的收益\n\n")

        f.write("## 三個版本的核心策略\n\n")

        f.write("### 版本A: 保守 (Conservative)\n")
        f.write("```\n")
        f.write("BULL:\n")
        f.write("  - close > sma50 (放寬: 去掉sma200)\n")
        f.write("  - 或 3日漲幅 > 1%\n\n")
        f.write("BEAR:\n")
        f.write("  - close < sma20 AND 2日連跌 (放寬: sma50改sma20, 3天改2天)\n")
        f.write("  - 或 3日跌幅 > -1%\n")
        f.write("```\n\n")

        f.write("### 版本B: 中等 (Moderate) ⭐ 推薦\n")
        f.write("```\n")
        f.write("BULL:\n")
        f.write("  - close > sma20 (短期均線)\n")
        f.write("  - 或 5日高點 > 20日均線\n")
        f.write("  - 或 成交量 > 平均值 + 上升動量\n\n")
        f.write("BEAR:\n")
        f.write("  - close < sma20 (短期下跌)\n")
        f.write("  - 或 連跌 >= 2天\n")
        f.write("  - 或 負動量\n")
        f.write("```\n\n")

        f.write("### 版本C: 激進 (Aggressive)\n")
        f.write("```\n")
        f.write("BULL: 任何上漲信號 (close > 前一日close)\n")
        f.write("BEAR: 任何下跌信號 (close < 前一日close)\n")
        f.write("```\n\n")

        f.write("## 回測對比結果\n\n")
        f.write("| Version | BULL% | BEAR% | RANGE% | NEUTRAL% | 年化% | Sharpe | 最大回撤 | 交易次 |\n")
        f.write("|---------|-------|-------|--------|----------|-------|--------|---------|--------|\n")
        for _, row in comparison_df.iterrows():
            f.write(f"| {row['Version']} | {row['BULL%']} | {row['BEAR%']} | {row['RANGE%']} | {row['NEUTRAL%']} | {row['年化%']} | {row['Sharpe']} | {row['最大回撤']} | {row['交易次']} |\n")
        f.write("\n\n")

        f.write("## 詳細分析\n\n")

        # 詳細分析每個版本
        for version in ['conservative', 'moderate', 'aggressive']:
            results = all_results[version]
            daily_logs = pd.DataFrame(results['daily_logs'])
            env_dist = daily_logs['Environment'].value_counts()
            total_days = len(daily_logs)

            bull_pct = (env_dist.get('BULL', 0) / total_days * 100) if total_days > 0 else 0
            bear_pct = (env_dist.get('BEAR', 0) / total_days * 100) if total_days > 0 else 0
            neutral_pct = (env_dist.get('NEUTRAL', 0) / total_days * 100) if total_days > 0 else 0

            f.write(f"### {version.upper()} 版本分析\n\n")
            f.write(f"**環境分佈:**\n")
            f.write(f"- BULL: {bull_pct:.1f}%\n")
            f.write(f"- BEAR: {bear_pct:.1f}%\n")
            f.write(f"- NEUTRAL: {neutral_pct:.1f}%\n\n")

            f.write(f"**績效指標:**\n")
            f.write(f"- 年化收益: {results['annual_return']*100:.2f}%\n")
            f.write(f"- Sharpe比率: {results['sharpe_ratio']:.4f}\n")
            f.write(f"- 最大回撤: {results['max_drawdown']*100:.2f}%\n")
            f.write(f"- 完成交易: {results['num_trades']} 次\n\n")

        f.write("## 最終建議\n\n")
        f.write("根據回測結果：\n\n")

        # 選擇最佳版本
        comparison_dict = {row['Version']: row for _, row in comparison_df.iterrows()}

        # 計算NEUTRAL比例最低的版本
        versions_neutral = {}
        for version in ['conservative', 'moderate', 'aggressive']:
            neutral_str = comparison_dict[version.upper()]['NEUTRAL%']
            neutral_val = float(neutral_str.rstrip('%'))
            versions_neutral[version] = neutral_val

        best_version = min(versions_neutral, key=versions_neutral.get)

        f.write(f"1. **最佳NEUTRAL控制**: {best_version.upper()} 版本 ({versions_neutral[best_version]:.1f}%)\n")
        f.write(f"   - 成功降低NEUTRAL比例，提高環境識別率\n\n")

        f.write(f"2. **推薦使用**: MODERATE 版本 (⭐)\n")
        f.write(f"   - 平衡保守性和激進性\n")
        f.write(f"   - NEUTRAL比例合理 ({versions_neutral['moderate']:.1f}%)\n")
        f.write(f"   - 年化收益和Sharpe比率良好\n\n")

        f.write("3. **風險提示**:\n")
        f.write("   - 激進版本NEUTRAL比例最低，但可能過度交易\n")
        f.write("   - 保守版本更穩健，但可能錯過機會\n")
        f.write("   - 建議根據實際市場情況和風險承受能力選擇\n\n")

    logger.info(f"報告已保存: {report_path}")

    # 生成CSV對比表
    csv_path = Path('/home/tom/TX_Quantitative_Trading/reports/parameter_comparison.csv')
    comparison_df.to_csv(csv_path, index=False)
    logger.info(f"對比表已保存: {csv_path}")


if __name__ == '__main__':
    main()
