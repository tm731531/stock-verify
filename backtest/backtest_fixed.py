#!/usr/bin/env python3
"""
台指期量化交易回測框架（修復版）
實現 3 種策略的完整回測和性能對比
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class SimpleBacktester:
    """簡化的回測引擎"""

    def __init__(self, data_file: str, initial_capital: float = 1_000_000):
        self.data_file = data_file
        self.initial_capital = initial_capital

        # 加載數據
        self.df = pd.read_csv(data_file)
        self.df['Date'] = pd.to_datetime(self.df['Date'])
        self.df = self.df.sort_values('Date').reset_index(drop=True)

        logger.info(f"✓ 回測引擎初始化")
        logger.info(f"  初始資金: ¥{initial_capital:,.0f}")
        logger.info(f"  交易日數: {len(self.df)}")
        logger.info(f"  日期範圍: {self.df['Date'].min().date()} ~ {self.df['Date'].max().date()}")

    def _add_indicators(self, df):
        """添加技術指標"""
        df = df.copy()

        # SMA
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['SMA50'] = df['Close'].rolling(50).mean()

        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 布林帶
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Up'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Low'] = df['BB_Mid'] - 2 * df['BB_Std']

        # 日收益率
        df['Ret'] = df['Close'].pct_change()

        return df

    def strategy_mean_reversion(self):
        """均值回歸策略"""
        df = self._add_indicators(self.df.copy())

        signals = [0] * len(df)

        for i in range(50, len(df)):
            # 買入: 價格 < 布林帶下軌 且 RSI < 30
            if df['Close'].iloc[i] < df['BB_Low'].iloc[i] and df['RSI'].iloc[i] < 30:
                signals[i] = 1  # 買入
            # 賣出: 價格 > 布林帶上軌 或 RSI > 70
            elif df['Close'].iloc[i] > df['BB_Up'].iloc[i] or df['RSI'].iloc[i] > 70:
                signals[i] = -1  # 賣出

        df['Signal'] = signals
        return df

    def strategy_trend_following(self):
        """趨勢跟蹤策略"""
        df = self._add_indicators(self.df.copy())

        signals = [0] * len(df)

        for i in range(50, len(df)):
            # 買入: 短期 SMA > 長期 SMA
            if df['SMA20'].iloc[i] > df['SMA50'].iloc[i]:
                if df['SMA20'].iloc[i-1] <= df['SMA50'].iloc[i-1]:
                    signals[i] = 1

            # 賣出: 短期 SMA < 長期 SMA
            if df['SMA20'].iloc[i] < df['SMA50'].iloc[i]:
                if df['SMA20'].iloc[i-1] >= df['SMA50'].iloc[i-1]:
                    signals[i] = -1

        df['Signal'] = signals
        return df

    def strategy_momentum(self):
        """動量策略"""
        df = self._add_indicators(self.df.copy())

        # 計算 20 日動量
        df['Momentum'] = df['Close'].pct_change(20)

        signals = [0] * len(df)

        for i in range(50, len(df)):
            # 動量 > 2% → 買入
            if df['Momentum'].iloc[i] > 0.02:
                signals[i] = 1
            # 動量 < -2% → 賣出
            elif df['Momentum'].iloc[i] < -0.02:
                signals[i] = -1

        df['Signal'] = signals
        return df

    def backtest(self, strategy_df):
        """執行回測並計算績效"""

        portfolio_value = [self.initial_capital]
        position = 0  # 0=空倉, 1=多倉
        entry_price = 0
        trades = []

        for i in range(1, len(strategy_df)):
            current_price = strategy_df['Close'].iloc[i]
            signal = strategy_df['Signal'].iloc[i]

            # 買入信號
            if signal == 1 and position == 0:
                entry_price = current_price
                position = 1
                trades.append({
                    'date': strategy_df['Date'].iloc[i],
                    'action': 'BUY',
                    'price': current_price
                })

            # 賣出信號
            elif signal == -1 and position == 1:
                exit_price = current_price
                profit = (exit_price - entry_price) / entry_price
                trades.append({
                    'date': strategy_df['Date'].iloc[i],
                    'action': 'SELL',
                    'price': exit_price,
                    'profit': profit
                })
                position = 0

            # 計算當前組合價值
            if position == 1:
                unrealized = (current_price - entry_price) / entry_price
                current_value = portfolio_value[0] * (1 + unrealized)
            else:
                current_value = portfolio_value[0]

            portfolio_value.append(current_value)

        # 計算績效指標
        portfolio_values = np.array(portfolio_value)
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital
        annual_return = total_return * (252 / len(strategy_df))

        # Sharpe Ratio
        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252) if np.std(daily_returns) > 0 else 0

        # 最大回撤
        cum_returns = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

        # 交易統計
        winning = len([t for t in trades if t.get('profit', 0) > 0])
        losing = len([t for t in trades if t.get('profit', 0) < 0])
        win_rate = winning / len(trades) if trades else 0

        # 獲利因子
        total_profit = sum([t.get('profit', 0) for t in trades if t.get('profit', 0) > 0])
        total_loss = abs(sum([t.get('profit', 0) for t in trades if t.get('profit', 0) < 0]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        metrics = {
            'Total Return (%)': round(total_return * 100, 2),
            'Annual Return (%)': round(annual_return * 100, 2),
            'Sharpe Ratio': round(sharpe, 2),
            'Max Drawdown (%)': round(max_drawdown * 100, 2),
            'Win Rate (%)': round(win_rate * 100, 2),
            'Profit Factor': round(profit_factor, 2),
            'Total Trades': len(trades),
            'Winning': winning,
            'Losing': losing,
            'Final Value': round(portfolio_values[-1], 0)
        }

        return metrics, trades, portfolio_values


def main():
    print("\n" + "=" * 80)
    print("🚀 台指期量化交易回測 - 三策略對比分析")
    print("=" * 80)

    backtester = SimpleBacktester(
        data_file='./taifex_data/TX_sample_2024_2026.csv',
        initial_capital=1_000_000
    )

    print("\n")

    # ========== 策略 1: 均值回歸 ==========
    logger.info("📊 策略 1: 均值回歸策略 (Mean Reversion)")
    logger.info("  邏輯: 價格突破布林帶 + RSI 極值")
    logger.info("  適用: 震盪市場\n")

    df1 = backtester.strategy_mean_reversion()
    metrics1, trades1, pv1 = backtester.backtest(df1)

    logger.info(f"  ✓ 交易次數: {metrics1['Total Trades']}")
    logger.info(f"  ✓ 總收益: {metrics1['Total Return (%)']}%")
    logger.info(f"  ✓ 年化報酬: {metrics1['Annual Return (%)']}%")
    logger.info(f"  ✓ Sharpe Ratio: {metrics1['Sharpe Ratio']}")
    logger.info(f"  ✓ 最大回撤: {metrics1['Max Drawdown (%)']}%")
    logger.info(f"  ✓ 勝率: {metrics1['Win Rate (%)']}%\n")

    # ========== 策略 2: 趨勢跟蹤 ==========
    logger.info("📊 策略 2: 趨勢跟蹤策略 (Trend Following)")
    logger.info("  邏輯: SMA 黃金叉/死亡叉")
    logger.info("  適用: 趨勢市場\n")

    df2 = backtester.strategy_trend_following()
    metrics2, trades2, pv2 = backtester.backtest(df2)

    logger.info(f"  ✓ 交易次數: {metrics2['Total Trades']}")
    logger.info(f"  ✓ 總收益: {metrics2['Total Return (%)']}%")
    logger.info(f"  ✓ 年化報酬: {metrics2['Annual Return (%)']}%")
    logger.info(f"  ✓ Sharpe Ratio: {metrics2['Sharpe Ratio']}")
    logger.info(f"  ✓ 最大回撤: {metrics2['Max Drawdown (%)']}%")
    logger.info(f"  ✓ 勝率: {metrics2['Win Rate (%)']}%\n")

    # ========== 策略 3: 動量策略 ==========
    logger.info("📊 策略 3: 動量策略 (Momentum)")
    logger.info("  邏輯: 20 日價格變化率")
    logger.info("  適用: 全市場\n")

    df3 = backtester.strategy_momentum()
    metrics3, trades3, pv3 = backtester.backtest(df3)

    logger.info(f"  ✓ 交易次數: {metrics3['Total Trades']}")
    logger.info(f"  ✓ 總收益: {metrics3['Total Return (%)']}%")
    logger.info(f"  ✓ 年化報酬: {metrics3['Annual Return (%)']}%")
    logger.info(f"  ✓ Sharpe Ratio: {metrics3['Sharpe Ratio']}")
    logger.info(f"  ✓ 最大回撤: {metrics3['Max Drawdown (%)']}%")
    logger.info(f"  ✓ 勝率: {metrics3['Win Rate (%)']}%\n")

    # ========== 總結 ==========
    print("\n" + "=" * 80)
    print("📈 三策略性能對比")
    print("=" * 80 + "\n")

    comparison = pd.DataFrame([metrics1, metrics2, metrics3],
                              index=['Mean Reversion', 'Trend Following', 'Momentum'])

    # 只顯示關鍵指標
    display_cols = ['Total Return (%)', 'Annual Return (%)', 'Sharpe Ratio',
                    'Max Drawdown (%)', 'Win Rate (%)', 'Total Trades']
    print(comparison[display_cols].to_string())

    print("\n")

    # 最佳策略
    best_sharpe = comparison['Sharpe Ratio'].idxmax()
    best_return = comparison['Total Return (%)'].idxmax()

    print(f"🏆 最佳 Sharpe Ratio 策略: {best_sharpe}")
    print(f"   Sharpe: {comparison.loc[best_sharpe, 'Sharpe Ratio']}")
    print(f"\n🏆 最高收益策略: {best_return}")
    print(f"   收益率: {comparison.loc[best_return, 'Total Return (%)']}%")

    # 保存結果
    results = {
        'Mean Reversion': {k: v for k, v in metrics1.items() if not isinstance(v, (list, dict))},
        'Trend Following': {k: v for k, v in metrics2.items() if not isinstance(v, (list, dict))},
        'Momentum': {k: v for k, v in metrics3.items() if not isinstance(v, (list, dict))}
    }

    with open('./taifex_data/backtest_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("\n✓ 結果已保存: ./taifex_data/backtest_results.json")

    print("\n" + "=" * 80)
    print("✅ 回測完成！")
    print("=" * 80 + "\n")

    return comparison


if __name__ == "__main__":
    results = main()
