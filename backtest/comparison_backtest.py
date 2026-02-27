#!/usr/bin/env python3
"""
對比回測：自適應 vs 單一策略 vs 買持策略

運行三個簡單的單一策略回測，與自適應系統進行對比
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class SimpleBacktester:
    """簡化的單策略回測器"""

    def __init__(self, df, initial_capital=1000000):
        self.df = df.copy()
        self.df['Date'] = pd.to_datetime(self.df['Date'])
        self.initial_capital = initial_capital
        self.contract_size = 200

    def add_indicators(self):
        """添加必需指標"""
        self.df['SMA20'] = self.df['Close'].rolling(20).mean()
        self.df['SMA50'] = self.df['Close'].rolling(50).mean()

        # 布林帶
        self.df['BB_Mid'] = self.df['Close'].rolling(20).mean()
        self.df['BB_Std'] = self.df['Close'].rolling(20).std()
        self.df['BB_Up'] = self.df['BB_Mid'] + 2 * self.df['BB_Std']
        self.df['BB_Low'] = self.df['BB_Mid'] - 2 * self.df['BB_Std']

        # RSI
        delta = self.df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        self.df['RSI'] = 100 - (100 / (1 + rs))

        # 高低點
        self.df['High20'] = self.df['High'].rolling(20).max()
        self.df['Low20'] = self.df['Low'].rolling(20).min()

    def backtest_sma_trend(self):
        """純 SMA 趨勢策略"""
        signals = [0] * len(self.df)
        for i in range(50, len(self.df)):
            if pd.notna(self.df['SMA20'].iloc[i]) and pd.notna(self.df['SMA50'].iloc[i]):
                if (self.df['SMA20'].iloc[i] > self.df['SMA50'].iloc[i] and
                    self.df['SMA20'].iloc[i-1] <= self.df['SMA50'].iloc[i-1]):
                    signals[i] = 1
                elif (self.df['SMA20'].iloc[i] < self.df['SMA50'].iloc[i] and
                      self.df['SMA20'].iloc[i-1] >= self.df['SMA50'].iloc[i-1]):
                    signals[i] = -1
        return self._run_backtest(signals, 'SMA趨勢')

    def backtest_mean_reversion(self):
        """純均值回歸策略"""
        signals = [0] * len(self.df)
        for i in range(50, len(self.df)):
            if pd.notna(self.df['BB_Low'].iloc[i]) and pd.notna(self.df['RSI'].iloc[i]):
                if self.df['Close'].iloc[i] < self.df['BB_Low'].iloc[i] and self.df['RSI'].iloc[i] < 30:
                    signals[i] = 1
                elif self.df['Close'].iloc[i] > self.df['BB_Up'].iloc[i] or self.df['RSI'].iloc[i] > 70:
                    signals[i] = -1
        return self._run_backtest(signals, '均值回歸')

    def backtest_breakout(self):
        """高低點突破策略"""
        signals = [0] * len(self.df)
        for i in range(20, len(self.df)):
            if pd.notna(self.df['High20'].iloc[i]) and pd.notna(self.df['Low20'].iloc[i]):
                if (self.df['Close'].iloc[i] > self.df['High20'].iloc[i-1] and
                    self.df['Close'].iloc[i-1] <= self.df['High20'].iloc[i-1]):
                    signals[i] = 1
                elif (self.df['Close'].iloc[i] < self.df['Low20'].iloc[i-1] and
                      self.df['Close'].iloc[i-1] >= self.df['Low20'].iloc[i-1]):
                    signals[i] = -1
        return self._run_backtest(signals, '高低突破')

    def backtest_hodl(self):
        """買持策略 (HODL)"""
        # HODL: 一開始就買入，然後一直持倒底
        signals = [0] * len(self.df)
        signals[50] = 1  # 第 50 天進場
        # 永遠不出場
        return self._run_backtest(signals, 'HODL買持', never_sell=True)

    def _run_backtest(self, signals, strategy_name, never_sell=False):
        """執行回測"""
        portfolio_values = [self.initial_capital]
        trades = []
        position = 0
        entry_price = 0
        entry_date = None

        for i in range(1, len(self.df)):
            current_price = self.df['Close'].iloc[i]
            current_date = self.df['Date'].iloc[i]
            signal = signals[i]

            if signal == 1 and position == 0:
                entry_price = current_price
                entry_date = current_date
                position = 1
                trades.append({'entry_date': entry_date, 'entry_price': entry_price})

            elif signal == -1 and position == 1:
                exit_price = current_price
                profit_pct = (exit_price - entry_price) / entry_price
                trades[-1].update({'exit_date': current_date, 'exit_price': exit_price, 'profit_pct': profit_pct})
                position = 0

            if position == 1:
                unrealized_pct = (current_price - entry_price) / entry_price
                current_value = self.initial_capital * (1 + unrealized_pct)
            else:
                current_value = self.initial_capital

            portfolio_values.append(current_value)

        # 如果持倉未平倉（HODL或信號不足）
        if position == 1 and not never_sell:
            final_price = self.df['Close'].iloc[-1]
            profit_pct = (final_price - entry_price) / entry_price
            trades[-1].update({'exit_date': self.df['Date'].iloc[-1], 'exit_price': final_price, 'profit_pct': profit_pct})

        # 計算績效
        portfolio_values = np.array(portfolio_values)
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital

        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]
        if np.std(daily_returns) > 0:
            sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
        else:
            sharpe = 0

        cummax = np.maximum.accumulate(portfolio_values)
        drawdown = (portfolio_values - cummax) / cummax
        max_drawdown = np.min(drawdown)

        num_trades = len([t for t in trades if 'exit_date' in t])

        return {
            'strategy': strategy_name,
            'total_return': total_return,
            'annual_return': total_return / 7,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'num_trades': num_trades,
            'num_signals': len([s for s in signals if s != 0]),
        }


def load_data(filepath):
    """加載數據"""
    df = pd.read_csv(filepath)
    df['Date'] = pd.to_datetime(df['Date'])
    return df.sort_values('Date').reset_index(drop=True)


def main():
    # 加載數據
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv'
    logger.info(f"加載數據: {data_file}")
    df = load_data(data_file)

    # 執行回測
    backtester = SimpleBacktester(df)
    backtester.add_indicators()

    logger.info("\n開始單一策略對比回測...\n")

    results = []
    results.append(backtester.backtest_sma_trend())
    results.append(backtester.backtest_mean_reversion())
    results.append(backtester.backtest_breakout())
    results.append(backtester.backtest_hodl())

    # 添加自適應策略結果 (已知數據)
    adaptive_result = {
        'strategy': '自適應系統',
        'total_return': 0.3324,
        'annual_return': 0.0475,
        'sharpe_ratio': 0.3134,
        'max_drawdown': -0.5344,
        'num_trades': 8,
        'num_signals': 25,  # 估計值
    }
    results.append(adaptive_result)

    # 打印對比表
    logger.info("=" * 100)
    logger.info("多策略對比分析 (2019-2026)")
    logger.info("=" * 100)

    logger.info(f"\n{'策略名稱':<15} {'總收益':<10} {'年化收益':<10} {'Sharpe':<10} {'最大回撤':<12} {'交易次數':<8} {'信號數':<8}")
    logger.info("-" * 100)

    for result in results:
        logger.info(
            f"{result['strategy']:<15} "
            f"{result['total_return']*100:>8.2f}%  "
            f"{result['annual_return']*100:>8.2f}%  "
            f"{result['sharpe_ratio']:>8.4f}  "
            f"{result['max_drawdown']*100:>10.2f}%  "
            f"{result['num_trades']:>7d}  "
            f"{result['num_signals']:>7d}"
        )

    # 排序並計算排名
    logger.info("\n" + "=" * 100)
    logger.info("績效排名 (按年化收益)")
    logger.info("=" * 100)

    ranked = sorted(results, key=lambda x: x['annual_return'], reverse=True)
    for idx, result in enumerate(ranked, 1):
        logger.info(f"{idx}. {result['strategy']:<20} 年化收益 {result['annual_return']*100:.2f}%")

    # 詳細分析
    logger.info("\n" + "=" * 100)
    logger.info("詳細分析")
    logger.info("=" * 100)

    for result in results:
        logger.info(f"\n{result['strategy']}:")
        logger.info(f"  總收益         : {result['total_return']*100:.2f}%")
        logger.info(f"  年化收益       : {result['annual_return']*100:.2f}%")
        logger.info(f"  Sharpe比率     : {result['sharpe_ratio']:.4f}")
        logger.info(f"  最大回撤       : {result['max_drawdown']*100:.2f}%")
        logger.info(f"  完成交易       : {result['num_trades']} 次")
        logger.info(f"  信號總數       : {result['num_signals']} 個")

    logger.info("\n" + "=" * 100)


if __name__ == '__main__':
    main()
