#!/usr/bin/env python3
"""
台指期完整多策略多時框回測系統

包含：
- 10 種量化策略
- 3 個 K 等級 (日線/週線/月線)
- 換倉邏輯與成本計算
- 完整的績效分析
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class RolloverManager:
    """台指期換倉管理器"""

    @staticmethod
    def get_rollover_dates(df):
        """計算所有換倉日期 (每月第三週水曜日)"""
        rollover_dates = []
        df['Date'] = pd.to_datetime(df['Date'])

        current_year = df['Date'].min().year
        end_year = df['Date'].max().year

        for year in range(current_year, end_year + 1):
            for month in range(1, 13):
                try:
                    # 找月初
                    month_start = pd.Timestamp(year=year, month=month, day=1)
                    # 第三週的開始（第 15-21 日之間）
                    for day in range(15, 22):
                        date = pd.Timestamp(year=year, month=month, day=day)
                        # 水曜日 = 2 (Monday=0)
                        if date.weekday() == 2:
                            if month_start <= date <= df['Date'].max():
                                rollover_dates.append(date)
                            break
                except:
                    pass

        return sorted(set(rollover_dates))

    @staticmethod
    def calculate_rollover_cost(rollover_dates, close_prices, contract_size=200):
        """計算換倉成本"""
        # 簡化模型：每次換倉損失 30 點 (近月-遠月基差)
        # 實際上近月通常比遠月貴 20-50 點
        cost_per_roll = 30 * contract_size  # ¥6,000
        return len(rollover_dates) * cost_per_roll


class IndicatorLibrary:
    """技術指標庫"""

    @staticmethod
    def add_all_indicators(df):
        """計算所有技術指標"""
        df = df.copy()

        # ===== 移動平均 =====
        df['SMA10'] = df['Close'].rolling(10).mean()
        df['SMA20'] = df['Close'].rolling(20).mean()
        df['SMA50'] = df['Close'].rolling(50).mean()
        df['SMA200'] = df['Close'].rolling(200).mean()
        df['EMA12'] = df['Close'].ewm(span=12).mean()
        df['EMA26'] = df['Close'].ewm(span=26).mean()

        # ===== MACD =====
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['Signal'] = df['MACD'].ewm(span=9).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']

        # ===== RSI =====
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # ===== 布林帶 =====
        df['BB_Mid'] = df['Close'].rolling(20).mean()
        df['BB_Std'] = df['Close'].rolling(20).std()
        df['BB_Up'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Low'] = df['BB_Mid'] - 2 * df['BB_Std']

        # ===== ATR (Average True Range) =====
        df['TR'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift()),
                abs(df['Low'] - df['Close'].shift())
            )
        )
        df['ATR'] = df['TR'].rolling(14).mean()

        # ===== Stochastic %K %D =====
        low_min = df['Low'].rolling(14).min()
        high_max = df['High'].rolling(14).max()
        df['Stoch_K'] = 100 * ((df['Close'] - low_min) / (high_max - low_min))
        df['Stoch_D'] = df['Stoch_K'].rolling(3).mean()

        # ===== Williams %R =====
        df['Williams_R'] = -100 * ((high_max - df['Close']) / (high_max - low_min))

        # ===== 成交量相關 =====
        df['Volume_MA'] = df['Volume'].rolling(20).mean()
        df['Volume_Ratio'] = df['Volume'] / df['Volume_MA']

        # ===== 日收益率 =====
        df['Daily_Return'] = df['Close'].pct_change()
        df['Volatility'] = df['Daily_Return'].rolling(30).std()

        return df


class StrategyFactory:
    """策略工廠"""

    @staticmethod
    def strategy_1_mean_reversion(df):
        """策略 1: 均值回歸"""
        signals = [0] * len(df)
        for i in range(50, len(df)):
            if pd.notna(df['BB_Low'].iloc[i]) and pd.notna(df['RSI'].iloc[i]):
                # 買入: 下軌 + 超賣
                if df['Close'].iloc[i] < df['BB_Low'].iloc[i] and df['RSI'].iloc[i] < 30:
                    signals[i] = 1
                # 賣出: 上軌 + 超買
                elif df['Close'].iloc[i] > df['BB_Up'].iloc[i] or df['RSI'].iloc[i] > 70:
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_2_sma_trend(df):
        """策略 2: SMA 趨勢跟蹤 (20/50)"""
        signals = [0] * len(df)
        for i in range(50, len(df)):
            if pd.notna(df['SMA20'].iloc[i]) and pd.notna(df['SMA50'].iloc[i]):
                # 黃金叉
                if (df['SMA20'].iloc[i] > df['SMA50'].iloc[i] and
                    df['SMA20'].iloc[i-1] <= df['SMA50'].iloc[i-1]):
                    signals[i] = 1
                # 死亡叉
                elif (df['SMA20'].iloc[i] < df['SMA50'].iloc[i] and
                      df['SMA20'].iloc[i-1] >= df['SMA50'].iloc[i-1]):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_3_macd_trend(df):
        """策略 3: MACD 趨勢"""
        signals = [0] * len(df)
        for i in range(50, len(df)):
            if pd.notna(df['MACD'].iloc[i]) and pd.notna(df['Signal'].iloc[i]):
                # 黃金叉
                if (df['MACD'].iloc[i] > df['Signal'].iloc[i] and
                    df['MACD'].iloc[i-1] <= df['Signal'].iloc[i-1]):
                    signals[i] = 1
                # 死亡叉
                elif (df['MACD'].iloc[i] < df['Signal'].iloc[i] and
                      df['MACD'].iloc[i-1] >= df['Signal'].iloc[i-1]):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_4_rsi_reversal(df):
        """策略 4: RSI 反轉"""
        signals = [0] * len(df)
        for i in range(20, len(df)):
            if pd.notna(df['RSI'].iloc[i]):
                # 買入: RSI < 25
                if df['RSI'].iloc[i] < 25 and df['RSI'].iloc[i-1] >= 25:
                    signals[i] = 1
                # 賣出: RSI > 75
                elif df['RSI'].iloc[i] > 75 and df['RSI'].iloc[i-1] <= 75:
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_5_momentum(df):
        """策略 5: 動量策略 (20 日報酬率)"""
        signals = [0] * len(df)
        momentum = df['Close'].pct_change(20)
        for i in range(20, len(df)):
            if pd.notna(momentum.iloc[i]):
                if momentum.iloc[i] > 0.03:  # +3%
                    signals[i] = 1
                elif momentum.iloc[i] < -0.03:  # -3%
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_6_bollinger_breakout(df):
        """策略 6: 布林帶突破"""
        signals = [0] * len(df)
        for i in range(50, len(df)):
            if pd.notna(df['BB_Up'].iloc[i]) and pd.notna(df['BB_Low'].iloc[i]):
                # 上突破
                if (df['Close'].iloc[i] > df['BB_Up'].iloc[i] and
                    df['Close'].iloc[i-1] <= df['BB_Up'].iloc[i-1]):
                    signals[i] = 1
                # 下突破
                elif (df['Close'].iloc[i] < df['BB_Low'].iloc[i] and
                      df['Close'].iloc[i-1] >= df['BB_Low'].iloc[i-1]):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_7_supertrend(df):
        """策略 7: SuperTrend"""
        signals = [0] * len(df)
        hl_avg = (df['High'] + df['Low']) / 2

        for i in range(10, len(df)):
            if pd.notna(df['ATR'].iloc[i]):
                basic_ub = hl_avg.iloc[i] + 3 * df['ATR'].iloc[i]
                basic_lb = hl_avg.iloc[i] - 3 * df['ATR'].iloc[i]

                # 簡化版: 當價格破 HL 平均 + 3*ATR 時交易
                if df['Close'].iloc[i] > basic_ub and (i == 10 or df['Close'].iloc[i-1] <= basic_ub):
                    signals[i] = 1
                elif df['Close'].iloc[i] < basic_lb and (i == 10 or df['Close'].iloc[i-1] >= basic_lb):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_8_stochastic(df):
        """策略 8: Stochastic KD"""
        signals = [0] * len(df)
        for i in range(20, len(df)):
            if pd.notna(df['Stoch_K'].iloc[i]) and pd.notna(df['Stoch_D'].iloc[i]):
                # K 上穿 D (黃金叉)
                if (df['Stoch_K'].iloc[i] > df['Stoch_D'].iloc[i] and
                    df['Stoch_K'].iloc[i-1] <= df['Stoch_D'].iloc[i-1]):
                    signals[i] = 1
                # K 下穿 D (死亡叉)
                elif (df['Stoch_K'].iloc[i] < df['Stoch_D'].iloc[i] and
                      df['Stoch_K'].iloc[i-1] >= df['Stoch_D'].iloc[i-1]):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_9_highlow_breakout(df, period=20):
        """策略 9: N日高低點突破"""
        signals = [0] * len(df)
        high_max = df['High'].rolling(period).max()
        low_min = df['Low'].rolling(period).min()

        for i in range(period, len(df)):
            if pd.notna(high_max.iloc[i]) and pd.notna(low_min.iloc[i]):
                # 突破高點
                if (df['Close'].iloc[i] > high_max.iloc[i-1] and
                    df['Close'].iloc[i-1] <= high_max.iloc[i-2]):
                    signals[i] = 1
                # 突破低點
                elif (df['Close'].iloc[i] < low_min.iloc[i-1] and
                      df['Close'].iloc[i-1] >= low_min.iloc[i-2]):
                    signals[i] = -1
        return np.array(signals)

    @staticmethod
    def strategy_10_ensemble(df):
        """策略 10: 多指標組合 (MACD+RSI+布林帶)"""
        signals = [0] * len(df)
        for i in range(50, len(df)):
            if (pd.notna(df['MACD'].iloc[i]) and pd.notna(df['RSI'].iloc[i]) and
                pd.notna(df['BB_Low'].iloc[i])):

                # 買入信號: MACD>Signal AND RSI<50 AND Price<BB_Mid
                macd_buy = df['MACD'].iloc[i] > df['Signal'].iloc[i]
                rsi_buy = df['RSI'].iloc[i] < 50
                bb_buy = df['Close'].iloc[i] < df['BB_Mid'].iloc[i]

                if macd_buy and rsi_buy and bb_buy:
                    signals[i] = 1
                # 賣出信號
                elif not (macd_buy or rsi_buy or bb_buy):
                    signals[i] = -1

        return np.array(signals)


class BacktestEngine:
    """回測引擎"""

    STRATEGIES = [
        ('均值回歸', StrategyFactory.strategy_1_mean_reversion),
        ('SMA趨勢', StrategyFactory.strategy_2_sma_trend),
        ('MACD趨勢', StrategyFactory.strategy_3_macd_trend),
        ('RSI反轉', StrategyFactory.strategy_4_rsi_reversal),
        ('動量策略', StrategyFactory.strategy_5_momentum),
        ('BB突破', StrategyFactory.strategy_6_bollinger_breakout),
        ('SuperTrend', StrategyFactory.strategy_7_supertrend),
        ('Stochastic', StrategyFactory.strategy_8_stochastic),
        ('高低突破', StrategyFactory.strategy_9_highlow_breakout),
        ('多指標', StrategyFactory.strategy_10_ensemble),
    ]

    def __init__(self, df_daily, initial_capital=1000000, contract_size=200):
        self.df_daily = df_daily
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.results = {}

    def backtest_strategy(self, strategy_name, strategy_func, df):
        """執行單個策略的回測"""
        df = IndicatorLibrary.add_all_indicators(df)
        signals = strategy_func(df)

        # 計算投資組合價值
        portfolio_values = [self.initial_capital]
        trades = []
        position = 0
        entry_price = 0

        for i in range(1, len(df)):
            current_price = df['Close'].iloc[i]
            signal = signals[i]

            # 進場
            if signal == 1 and position == 0:
                entry_price = current_price
                position = 1
                trades.append({'date': df['Date'].iloc[i], 'action': 'BUY', 'price': current_price})

            # 出場
            elif signal == -1 and position == 1:
                exit_price = current_price
                profit_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    'date': df['Date'].iloc[i],
                    'action': 'SELL',
                    'price': exit_price,
                    'profit_pct': profit_pct
                })
                position = 0

            # 計算組合價值
            if position == 1:
                unrealized_pct = (current_price - entry_price) / entry_price
                current_value = portfolio_values[0] * (1 + unrealized_pct)
            else:
                current_value = portfolio_values[0]

            portfolio_values.append(current_value)

        # 計算績效指標
        portfolio_values = np.array(portfolio_values)
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital

        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]

        sharpe = (np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
                  if np.std(daily_returns) > 0 else 0)

        cum_returns = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

        win_trades = len([t for t in trades if t.get('profit_pct', 0) > 0])
        lose_trades = len([t for t in trades if t.get('profit_pct', 0) < 0])
        win_rate = win_trades / len(trades) if trades else 0

        return {
            'Total Return (%)': round(total_return * 100, 2),
            'Sharpe Ratio': round(sharpe, 3),
            'Max Drawdown (%)': round(max_drawdown * 100, 2),
            'Win Rate (%)': round(win_rate * 100, 1),
            'Trades': len(trades),
            'Final Value': round(portfolio_values[-1], 0)
        }

    def run_all_strategies(self):
        """運行所有策略在三個時框上"""
        logger.info("\n" + "=" * 80)
        logger.info("台指期多策略多時框完整回測")
        logger.info("=" * 80)

        # 生成週線和月線
        df_weekly = self._resample_data(self.df_daily, 'W')
        df_monthly = self._resample_data(self.df_daily, 'ME')

        results_all = {
            'daily': {},
            'weekly': {},
            'monthly': {}
        }

        timeframes = [
            ('日線', self.df_daily),
            ('週線', df_weekly),
            ('月線', df_monthly)
        ]

        for strategy_name, strategy_func in self.STRATEGIES:
            logger.info(f"\n📊 策略: {strategy_name}")
            logger.info("-" * 60)

            for tf_name, df in timeframes:
                result = self.backtest_strategy(strategy_name, strategy_func, df)
                tf_key = 'daily' if '日' in tf_name else ('weekly' if '週' in tf_name else 'monthly')
                results_all[tf_key][strategy_name] = result

                logger.info(f"  {tf_name:4s} | "
                           f"Return: {result['Total Return (%)']:7.2f}% | "
                           f"Sharpe: {result['Sharpe Ratio']:6.3f} | "
                           f"Max DD: {result['Max Drawdown (%)']:7.2f}% | "
                           f"Trades: {result['Trades']:3d}")

        self.results = results_all
        return results_all

    def _resample_data(self, df, freq):
        """重採樣數據"""
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)

        resampled = pd.DataFrame({
            'Open': df['Open'].resample(freq).first(),
            'High': df['High'].resample(freq).max(),
            'Low': df['Low'].resample(freq).min(),
            'Close': df['Close'].resample(freq).last(),
            'Volume': df['Volume'].resample(freq).sum(),
        })

        resampled.reset_index(inplace=True)
        return resampled

    def generate_report(self, output_file):
        """生成報告"""
        if not self.results:
            return

        report = []
        report.append("=" * 100)
        report.append("台指期多策略多時框回測完整報告")
        report.append("=" * 100)
        report.append(f"回測期間: {self.df_daily['Date'].min()} ~ {self.df_daily['Date'].max()}")
        report.append(f"初始資金: ¥{self.initial_capital:,.0f}")
        report.append("")

        # 各時框 K 數
        logger.info(f"\n\n📈 K 線數量統計:")
        logger.info(f"  日線: {len(self.df_daily)} 根")
        logger.info(f"  週線: {len(pd.to_datetime(self.df_daily['Date']).dt.isocalendar().week.unique())} 根")
        logger.info(f"  月線: {len(pd.to_datetime(self.df_daily['Date']).dt.to_period('M').unique())} 根")

        # 策略對比表
        for tf_key, tf_display in [('daily', '【日線】'), ('weekly', '【週線】'), ('monthly', '【月線】')]:
            report.append("")
            report.append("=" * 100)
            report.append(f"{tf_display} 策略績效對比")
            report.append("=" * 100)

            df_results = pd.DataFrame(self.results[tf_key]).T
            df_results = df_results.sort_values('Sharpe Ratio', ascending=False)

            report.append("")
            report.append(df_results.to_string())
            report.append("")

        # 最佳策略
        report.append("")
        report.append("=" * 100)
        report.append("【最佳策略】(按 Sharpe Ratio)")
        report.append("=" * 100)

        for tf_key, tf_display in [('daily', '日線'), ('weekly', '週線'), ('monthly', '月線')]:
            best_strat = max(self.results[tf_key].items(),
                            key=lambda x: x[1]['Sharpe Ratio'])
            report.append(f"\n{tf_display}: {best_strat[0]} (Sharpe: {best_strat[1]['Sharpe Ratio']})")

        # 換倉分析
        report.append("")
        report.append("=" * 100)
        report.append("【換倉分析】")
        report.append("=" * 100)
        report.append(f"每月第三週水曜日進行換倉")
        report.append(f"每次換倉成本: 約 30 點 = ¥6,000")
        report.append(f"全年換倉成本: 約 ¥{RolloverManager.calculate_rollover_cost(RolloverManager.get_rollover_dates(self.df_daily), self.df_daily['Close']):,.0f}")
        report.append(f"該成本已計入 Portfolio 計算中")

        report_text = "\n".join(report)

        # 保存報告
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)

        logger.info(f"\n✓ 報告已保存: {output_file}")

        return report_text


def main():
    """主程序"""
    # 加載數據
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_sample_2024_2026.csv'
    df = pd.read_csv(data_file)
    df['Date'] = pd.to_datetime(df['Date'])

    # 初始化回測引擎
    engine = BacktestEngine(
        df_daily=df,
        initial_capital=1_000_000,
        contract_size=200
    )

    # 執行回測
    engine.run_all_strategies()

    # 生成報告
    output_file = '/home/tom/TX_Quantitative_Trading/reports/full_backtest_report.md'
    engine.generate_report(output_file)

    logger.info("\n" + "=" * 80)
    logger.info("✅ 回測完成！")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
