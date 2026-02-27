#!/usr/bin/env python3
"""
台指期量化交易回測框架

實現多種量化策略:
1. 均值回歸策略 (Mean Reversion)
2. 趨勢跟蹤策略 (Trend Following)
3. 動量策略 (Momentum)
4. 組合策略 (Ensemble)

性能指標:
- Sharpe Ratio, Sortino Ratio
- 最大回撤, 勝率, 獲利因子
- 累積收益, 年化報酬率
"""

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class QuantitativeBacktester:
    """量化交易回測引擎"""

    def __init__(self, data_file: str, initial_capital: float = 1_000_000,
                 contract_size: float = 1, transaction_cost: float = 0.001):
        """
        初始化回測引擎

        Args:
            data_file: CSV 數據檔案路徑
            initial_capital: 初始資金 (台幣)
            contract_size: 合約面值 (台指期為 200 元/點)
            transaction_cost: 手續費率 (0.1%)
        """
        self.data_file = data_file
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.transaction_cost = transaction_cost

        # 加載數據
        self.data = self._load_data()
        self.original_data = self.data.copy()

        # 初始化回測結果
        self.positions = None
        self.portfolio_value = None
        self.trades = []
        self.signals = None

        logger.info(f"✓ 回測引擎初始化完成")
        logger.info(f"  數據檔: {data_file}")
        logger.info(f"  初始資金: ¥{initial_capital:,.0f}")
        logger.info(f"  數據範圍: {self.data['Date'].min().date()} ~ {self.data['Date'].max().date()}")

    def _load_data(self) -> pd.DataFrame:
        """加載 CSV 數據"""
        try:
            df = pd.read_csv(self.data_file)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"數據加載失敗: {e}")
            raise

    def _calculate_indicators(self) -> pd.DataFrame:
        """計算技術指標"""
        df = self.data.copy()

        # 簡單移動平均 (SMA)
        df['SMA_20'] = df['Close'].rolling(20).mean()
        df['SMA_50'] = df['Close'].rolling(50).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()

        # 指數移動平均 (EMA)
        df['EMA_12'] = df['Close'].ewm(span=12).mean()
        df['EMA_26'] = df['Close'].ewm(span=26).mean()

        # MACD
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']

        # RSI (相對強度指數)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 布林帶
        df['BB_Middle'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * 2)
        df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * 2)

        # 日收益率
        df['Daily_Return'] = df['Close'].pct_change()

        # 波動率 (30日歷史波動)
        df['Volatility'] = df['Daily_Return'].rolling(30).std()

        return df

    # ========== 策略 1: 均值回歸策略 ==========
    def strategy_mean_reversion(self, short_window=20, long_window=50,
                                 rsi_threshold=30, rsi_overbought=70) -> pd.DataFrame:
        """
        均值回歸策略

        邏輯:
        - 價格跌破下軌 + RSI < 30 → 買入
        - 價格漲破上軌 + RSI > 70 → 賣出

        適用於: 震盪市場，高效
        """
        logger.info("\n" + "=" * 70)
        logger.info("策略 1: 均值回歸策略 (Mean Reversion)")
        logger.info("=" * 70)

        df = self._calculate_indicators()

        # 交易信號
        df['Signal'] = 0

        # 買入信號: 價格在下軌 & RSI 低
        buy_condition = (df['Close'] < df['BB_Lower']) & (df['RSI'] < rsi_threshold)
        df.loc[buy_condition, 'Signal'] = 1

        # 賣出信號: 價格在上軌 & RSI 高
        sell_condition = (df['Close'] > df['BB_Upper']) & (df['RSI'] > rsi_overbought)
        df.loc[sell_condition, 'Signal'] = -1

        # 持倉信號 (填充）
        df['Position'] = 0
        in_position = False
        for i in range(len(df)):
            if df['Signal'].iloc[i] == 1:
                in_position = True
            elif df['Signal'].iloc[i] == -1:
                in_position = False
            if in_position:
                df['Position'].iloc[i] = 1

        logger.info(f"交易信號統計:")
        logger.info(f"  買入次數: {(df['Signal'] == 1).sum()}")
        logger.info(f"  賣出次數: {(df['Signal'] == -1).sum()}")

        return df

    # ========== 策略 2: 趨勢跟蹤策略 ==========
    def strategy_trend_following(self, fast_window=12, slow_window=26) -> pd.DataFrame:
        """
        趨勢跟蹤策略 (MACD)

        邏輯:
        - MACD > Signal → 買入
        - MACD < Signal → 賣出

        適用於: 趨勢市場，低振盪
        """
        logger.info("\n" + "=" * 70)
        logger.info("策略 2: 趨勢跟蹤策略 (Trend Following - MACD)")
        logger.info("=" * 70)

        df = self._calculate_indicators()

        # 交易信號
        df['Signal'] = 0

        # MACD 黃金叉
        buy_condition = (df['MACD'] > df['Signal']) & (df['MACD'].shift(1) <= df['Signal'].shift(1))
        df.loc[buy_condition, 'Signal'] = 1

        # MACD 死亡叉
        sell_condition = (df['MACD'] < df['Signal']) & (df['MACD'].shift(1) >= df['Signal'].shift(1))
        df.loc[sell_condition, 'Signal'] = -1

        # 持倉信號
        df['Position'] = 0
        in_position = False
        for i in range(len(df)):
            if df['Signal'].iloc[i] == 1:
                in_position = True
            elif df['Signal'].iloc[i] == -1:
                in_position = False
            if in_position:
                df['Position'].iloc[i] = 1

        logger.info(f"交易信號統計:")
        logger.info(f"  買入次數: {(df['Signal'] == 1).sum()}")
        logger.info(f"  賣出次數: {(df['Signal'] == -1).sum()}")

        return df

    # ========== 策略 3: 動量策略 ==========
    def strategy_momentum(self, momentum_window=20, threshold=0.02) -> pd.DataFrame:
        """
        動量策略

        邏輯:
        - 過去 N 日漲幅 > 閾值 → 買入
        - 過去 N 日漲幅 < -閾值 → 賣出

        適用於: 各種市場
        """
        logger.info("\n" + "=" * 70)
        logger.info("策略 3: 動量策略 (Momentum)")
        logger.info("=" * 70)

        df = self._calculate_indicators()

        # 計算動量
        df['Momentum'] = (df['Close'] / df['Close'].shift(momentum_window) - 1)

        # 交易信號
        df['Signal'] = 0
        df.loc[df['Momentum'] > threshold, 'Signal'] = 1
        df.loc[df['Momentum'] < -threshold, 'Signal'] = -1

        # 持倉信號
        df['Position'] = 0
        in_position = False
        for i in range(len(df)):
            if df['Signal'].iloc[i] == 1:
                in_position = True
            elif df['Signal'].iloc[i] == -1:
                in_position = False
            if in_position:
                df['Position'].iloc[i] = 1

        logger.info(f"交易信號統計:")
        logger.info(f"  買入次數: {(df['Signal'] == 1).sum()}")
        logger.info(f"  賣出次數: {(df['Signal'] == -1).sum()}")

        return df

    def _calculate_portfolio_value(self, df: pd.DataFrame) -> tuple:
        """計算投資組合價值和回報"""

        cash = self.initial_capital
        shares = 0
        portfolio_values = []
        daily_returns = []
        trades_log = []

        for i in range(len(df)):
            current_price = df['Close'].iloc[i]

            # 買入信號
            if df['Signal'].iloc[i] == 1 and shares == 0:
                # 買入 1 口合約 (點數 * 200)
                contract_value = current_price * self.contract_size
                transaction_fee = contract_value * self.transaction_cost

                if cash >= (contract_value + transaction_fee):
                    shares = 1
                    entry_price = current_price
                    cash -= (contract_value + transaction_fee)

                    trades_log.append({
                        'Date': df['Date'].iloc[i],
                        'Action': 'BUY',
                        'Price': current_price,
                        'Quantity': 1
                    })

            # 賣出信號
            elif df['Signal'].iloc[i] == -1 and shares == 1:
                contract_value = current_price * self.contract_size
                transaction_fee = contract_value * self.transaction_cost

                profit = (current_price - entry_price) * self.contract_size - transaction_fee
                cash += (contract_value - transaction_fee)
                shares = 0

                trades_log.append({
                    'Date': df['Date'].iloc[i],
                    'Action': 'SELL',
                    'Price': current_price,
                    'Profit': profit
                })

            # 計算組合價值
            if shares == 1:
                position_value = current_price * self.contract_size
                total_value = cash + position_value
            else:
                total_value = cash

            portfolio_values.append(total_value)

        self.trades = trades_log
        return np.array(portfolio_values), np.array(daily_returns)

    def backtest(self, strategy_func, **strategy_params) -> dict:
        """執行回測"""

        # 運行策略
        df = strategy_func(**strategy_params)

        # 計算投資組合價值
        portfolio_values, daily_returns = self._calculate_portfolio_value(df)

        # 計算績效指標
        metrics = self._calculate_metrics(portfolio_values, daily_returns, df)

        return {
            'data': df,
            'portfolio_values': portfolio_values,
            'daily_returns': daily_returns,
            'metrics': metrics,
            'trades': self.trades
        }

    def _calculate_metrics(self, portfolio_values: np.ndarray,
                          daily_returns: np.ndarray, df: pd.DataFrame) -> dict:
        """計算績效指標"""

        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital
        annual_return = total_return / (len(df) / 252)  # 假設 252 個交易日/年

        # 計算每日收益率
        daily_pnl = np.diff(portfolio_values)
        daily_ret = daily_pnl / portfolio_values[:-1]

        # Sharpe Ratio (無風險率 2%)
        risk_free_rate = 0.02 / 252
        excess_returns = daily_ret - risk_free_rate
        sharpe_ratio = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252) if np.std(excess_returns) > 0 else 0

        # Sortino Ratio (只看下跌)
        downside_returns = excess_returns[excess_returns < 0]
        sortino_ratio = np.mean(excess_returns) / np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 0 else 0

        # 最大回撤
        cumulative = np.cumprod(1 + daily_ret)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = np.min(drawdown)

        # 勝率和獲利因子
        winning_trades = len([t for t in self.trades if t.get('Profit', 0) > 0])
        losing_trades = len([t for t in self.trades if t.get('Profit', 0) < 0])
        win_rate = winning_trades / (winning_trades + losing_trades) if (winning_trades + losing_trades) > 0 else 0

        total_profit = sum([t.get('Profit', 0) for t in self.trades if t.get('Profit', 0) > 0])
        total_loss = abs(sum([t.get('Profit', 0) for t in self.trades if t.get('Profit', 0) < 0]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        return {
            'Total Return (%)': round(total_return * 100, 2),
            'Annual Return (%)': round(annual_return * 100, 2),
            'Sharpe Ratio': round(sharpe_ratio, 2),
            'Sortino Ratio': round(sortino_ratio, 2),
            'Max Drawdown (%)': round(max_drawdown * 100, 2),
            'Win Rate (%)': round(win_rate * 100, 2),
            'Profit Factor': round(profit_factor, 2),
            'Total Trades': len(self.trades),
            'Winning Trades': winning_trades,
            'Losing Trades': losing_trades,
            'Final Portfolio Value': round(portfolio_values[-1], 0)
        }

    def print_results(self, results: dict, strategy_name: str):
        """打印回測結果"""

        logger.info("\n" + "=" * 70)
        logger.info(f"📊 回測結果: {strategy_name}")
        logger.info("=" * 70)

        metrics = results['metrics']
        logger.info(f"\n💰 收益指標:")
        logger.info(f"  總收益率: {metrics['Total Return (%)']}%")
        logger.info(f"  年化收益率: {metrics['Annual Return (%)']}%")
        logger.info(f"  最終組合價值: ¥{metrics['Final Portfolio Value']:,.0f}")

        logger.info(f"\n📈 風險指標:")
        logger.info(f"  Sharpe Ratio: {metrics['Sharpe Ratio']}")
        logger.info(f"  Sortino Ratio: {metrics['Sortino Ratio']}")
        logger.info(f"  最大回撤: {metrics['Max Drawdown (%)']}%")

        logger.info(f"\n📊 交易指標:")
        logger.info(f"  總交易次數: {metrics['Total Trades']}")
        logger.info(f"  勝率: {metrics['Win Rate (%)']}%")
        logger.info(f"  獲利因子: {metrics['Profit Factor']}")
        logger.info(f"  贏利交易: {metrics['Winning Trades']}")
        logger.info(f"  虧損交易: {metrics['Losing Trades']}")

        logger.info("\n" + "=" * 70)

        return metrics


def main():
    """主程序 - 運行多策略回測"""

    print("\n" + "🚀 " * 35)
    print("台指期量化交易回測框架")
    print("🚀 " * 35)

    # 初始化回測引擎
    backtester = QuantitativeBacktester(
        data_file='./taifex_data/TX_sample_2024_2026.csv',
        initial_capital=1_000_000,
        contract_size=200  # 台指期: 1 點 = 200 元
    )

    # 結果存儲
    all_results = {}

    # ========== 策略 1: 均值回歸 ==========
    logger.info("\n開始回測策略 1...")
    results_mr = backtester.backtest(
        backtester.strategy_mean_reversion,
        short_window=20,
        long_window=50,
        rsi_threshold=30
    )
    metrics_mr = backtester.print_results(results_mr, "均值回歸策略")
    all_results['Mean Reversion'] = metrics_mr

    # 重置回測器
    backtester.data = backtester.original_data.copy()

    # ========== 策略 2: 趨勢跟蹤 ==========
    logger.info("\n開始回測策略 2...")
    results_tf = backtester.backtest(
        backtester.strategy_trend_following,
        fast_window=12,
        slow_window=26
    )
    metrics_tf = backtester.print_results(results_tf, "趨勢跟蹤策略")
    all_results['Trend Following'] = metrics_tf

    # 重置回測器
    backtester.data = backtester.original_data.copy()

    # ========== 策略 3: 動量策略 ==========
    logger.info("\n開始回測策略 3...")
    results_mom = backtester.backtest(
        backtester.strategy_momentum,
        momentum_window=20,
        threshold=0.02
    )
    metrics_mom = backtester.print_results(results_mom, "動量策略")
    all_results['Momentum'] = metrics_mom

    # ========== 總結對比 ==========
    logger.info("\n" + "=" * 70)
    logger.info("📊 三策略對比總結")
    logger.info("=" * 70)

    comparison_df = pd.DataFrame(all_results).T
    logger.info("\n" + comparison_df.to_string())

    # 找最佳策略
    best_strategy = comparison_df['Sharpe Ratio'].idxmax()
    logger.info(f"\n🏆 最佳策略 (Sharpe Ratio 最高): {best_strategy}")
    logger.info(f"   Sharpe Ratio: {comparison_df.loc[best_strategy, 'Sharpe Ratio']}")

    # 保存結果
    results_file = './taifex_data/backtest_results.json'
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    logger.info(f"\n✓ 結果已保存: {results_file}")

    logger.info("\n" + "=" * 70)
    logger.info("✅ 回測完成！")
    logger.info("=" * 70)

    return all_results


if __name__ == "__main__":
    results = main()
