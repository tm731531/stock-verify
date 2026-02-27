#!/usr/bin/env python3
"""
台指期日線完整策略回測系統（2019-2026 完整數據）

包含：
- 10 種量化策略（日線級別）
- 2019-2026 完整 1732 根 K 線數據
- 換倉成本計算（月換倉，成本 ¥6,100）
- 年度分層績效分析
- 市場環境分析（牛熊市、暴跌、反彈）
- 詳細的人類可讀報告
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
from collections import defaultdict

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
        df_copy = df.copy()
        if isinstance(df_copy['Date'].iloc[0], str):
            df_copy['Date'] = pd.to_datetime(df_copy['Date'])
        else:
            df_copy['Date'] = pd.to_datetime(df_copy['Date'])

        current_year = df_copy['Date'].min().year
        end_year = df_copy['Date'].max().year
        max_date = df_copy['Date'].max()

        for year in range(current_year, end_year + 1):
            for month in range(1, 13):
                try:
                    # 找月初
                    month_start = pd.Timestamp(year=year, month=month, day=1)
                    # 第三週的開始（第 15-21 日之間）
                    for day in range(15, 22):
                        try:
                            date = pd.Timestamp(year=year, month=month, day=day)
                            # 水曜日 = 2 (Monday=0)
                            if date.weekday() == 2:
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
        # 每次換倉成本 = 30點基差 × 200元/點 + 100手續費 = ¥6,100
        cost_per_roll = 6100
        total_cost = len(rollover_dates) * cost_per_roll
        return {
            'num_rollovers': len(rollover_dates),
            'cost_per_roll': cost_per_roll,
            'total_cost': total_cost,
            'rollover_dates': rollover_dates
        }


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
        self.df_daily = df_daily.copy()
        self.df_daily['Date'] = pd.to_datetime(self.df_daily['Date'])
        self.initial_capital = initial_capital
        self.contract_size = contract_size
        self.results = {}
        self.annual_results = defaultdict(dict)
        self.rollover_cost_info = RolloverManager.calculate_rollover_cost(
            RolloverManager.get_rollover_dates(self.df_daily)
        )

    def backtest_strategy(self, strategy_name, strategy_func, df):
        """執行單個策略的回測"""
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'])

        df = IndicatorLibrary.add_all_indicators(df)
        signals = strategy_func(df)

        # 計算投資組合價值
        portfolio_values = [self.initial_capital]
        trades = []
        position = 0
        entry_price = 0
        entry_date = None

        for i in range(1, len(df)):
            current_price = df['Close'].iloc[i]
            signal = signals[i]

            # 進場
            if signal == 1 and position == 0:
                entry_price = current_price
                entry_date = df['Date'].iloc[i]
                position = 1
                trades.append({
                    'date': entry_date,
                    'action': 'BUY',
                    'price': current_price
                })

            # 出場
            elif signal == -1 and position == 1:
                exit_price = current_price
                profit_pct = (exit_price - entry_price) / entry_price
                trades.append({
                    'date': df['Date'].iloc[i],
                    'action': 'SELL',
                    'price': exit_price,
                    'profit_pct': profit_pct,
                    'days_held': (df['Date'].iloc[i] - entry_date).days
                })
                position = 0

            # 計算組合價值
            if position == 1:
                unrealized_pct = (current_price - entry_price) / entry_price
                current_value = self.initial_capital * (1 + unrealized_pct)
            else:
                current_value = self.initial_capital

            portfolio_values.append(current_value)

        # 計算績效指標
        portfolio_values = np.array(portfolio_values)
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital

        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]

        if np.std(daily_returns) > 0:
            sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
        else:
            sharpe = 0

        cum_returns = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

        win_trades = len([t for t in trades if t.get('profit_pct', 0) > 0])
        lose_trades = len([t for t in trades if t.get('profit_pct', 0) < 0])
        total_trades = len([t for t in trades if t.get('profit_pct') is not None])
        win_rate = win_trades / total_trades if total_trades > 0 else 0

        # 計算換倉成本影響
        rollover_cost_impact = self.rollover_cost_info['total_cost'] / self.initial_capital
        adjusted_return = total_return - rollover_cost_impact

        return {
            'Total Return (%)': round(total_return * 100, 2),
            'Adjusted Return (%)': round(adjusted_return * 100, 2),
            'Sharpe Ratio': round(sharpe, 3),
            'Max Drawdown (%)': round(max_drawdown * 100, 2),
            'Win Rate (%)': round(win_rate * 100, 1),
            'Trades': total_trades,
            'Final Value': round(portfolio_values[-1], 0),
            'Trades Detail': trades,
            'Portfolio Values': portfolio_values,
            'Dates': df['Date'].values
        }

    def backtest_strategy_annual(self, strategy_name, strategy_func, df):
        """執行策略回測並按年度分層"""
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'])
        df = IndicatorLibrary.add_all_indicators(df)
        signals = strategy_func(df)

        # 按年份分割
        years = sorted(df['Date'].dt.year.unique())
        annual_results = {}

        for year in years:
            year_mask = df['Date'].dt.year == year
            df_year = df[year_mask].reset_index(drop=True)
            signals_year = signals[year_mask]

            if len(df_year) < 50:
                continue

            # 回測該年度
            portfolio_values = [self.initial_capital]
            trades = []
            position = 0
            entry_price = 0

            for i in range(1, len(df_year)):
                current_price = df_year['Close'].iloc[i]
                signal = signals_year[i]

                # 進場
                if signal == 1 and position == 0:
                    entry_price = current_price
                    position = 1
                    trades.append({'action': 'BUY', 'price': current_price})

                # 出場
                elif signal == -1 and position == 1:
                    exit_price = current_price
                    profit_pct = (exit_price - entry_price) / entry_price
                    trades.append({
                        'action': 'SELL',
                        'price': exit_price,
                        'profit_pct': profit_pct
                    })
                    position = 0

                # 計算組合價值
                if position == 1:
                    unrealized_pct = (current_price - entry_price) / entry_price
                    current_value = self.initial_capital * (1 + unrealized_pct)
                else:
                    current_value = self.initial_capital

                portfolio_values.append(current_value)

            # 計算該年度績效
            portfolio_values = np.array(portfolio_values)
            year_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital

            daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]

            if np.std(daily_returns) > 0:
                year_sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
            else:
                year_sharpe = 0

            total_trades = len([t for t in trades if t.get('profit_pct') is not None])
            win_trades = len([t for t in trades if t.get('profit_pct', 0) > 0])
            win_rate = win_trades / total_trades if total_trades > 0 else 0

            annual_results[year] = {
                'Return (%)': round(year_return * 100, 2),
                'Sharpe': round(year_sharpe, 3),
                'Trades': total_trades,
                'Win Rate (%)': round(win_rate * 100, 1),
                'Final Value': round(portfolio_values[-1], 0)
            }

        return annual_results

    def run_all_strategies(self):
        """執行所有策略的回測"""
        logger.info("\n" + "=" * 100)
        logger.info("台指期日線完整策略回測 (2019-2026)")
        logger.info("=" * 100)
        logger.info(f"數據期間: {self.df_daily['Date'].min().date()} ~ {self.df_daily['Date'].max().date()}")
        logger.info(f"總 K 線數: {len(self.df_daily)} 根")
        logger.info(f"初始資金: ¥{self.initial_capital:,.0f}")
        logger.info(f"換倉次數: {self.rollover_cost_info['num_rollovers']} 次")
        logger.info(f"換倉總成本: ¥{self.rollover_cost_info['total_cost']:,.0f}")
        logger.info("")

        results_all = {}
        annual_results_all = {}

        for strategy_name, strategy_func in self.STRATEGIES:
            logger.info(f"執行策略: {strategy_name}")

            # 全期回測
            result = self.backtest_strategy(strategy_name, strategy_func, self.df_daily)
            results_all[strategy_name] = result

            # 年度分層
            annual_result = self.backtest_strategy_annual(strategy_name, strategy_func, self.df_daily)
            annual_results_all[strategy_name] = annual_result

            logger.info(f"  總收益: {result['Total Return (%)']:.2f}% | "
                       f"Sharpe: {result['Sharpe Ratio']:.3f} | "
                       f"交易次數: {result['Trades']} | "
                       f"勝率: {result['Win Rate (%)']:.1f}%")

        self.results = results_all
        self.annual_results = annual_results_all

        return results_all, annual_results_all

    def generate_report(self, output_file, json_output_file=None):
        """生成詳細的人類可讀報告"""
        if not self.results:
            return

        report = []

        # ============ 標題 ============
        report.append("=" * 120)
        report.append("台指期日線完整策略回測報告 (2019-2026)")
        report.append("=" * 120)
        report.append("")

        # ============ 數據信息 ============
        report.append("【回測基本信息】")
        report.append("-" * 120)
        report.append(f"回測期間: {self.df_daily['Date'].min().date()} ~ {self.df_daily['Date'].max().date()}")
        report.append(f"總交易日數: {len(self.df_daily)} 根 K 線")
        report.append(f"初始資金: ¥{self.initial_capital:,.0f}")
        report.append(f"合約規格: 台指期，1 口 = 200 元/點")
        report.append("")

        # ============ 換倉成本 ============
        report.append("【換倉成本分析】")
        report.append("-" * 120)
        report.append(f"換倉策略: 每月第三個週三自動換倉")
        report.append(f"換倉次數: {self.rollover_cost_info['num_rollovers']} 次")
        report.append(f"單次換倉成本: ¥{self.rollover_cost_info['cost_per_roll']:,.0f} (30點基差 × 200元 + 100元手續費)")
        report.append(f"總換倉成本: ¥{self.rollover_cost_info['total_cost']:,.0f}")
        report.append(f"成本對初始資金比率: {self.rollover_cost_info['total_cost'] / self.initial_capital * 100:.3f}%")
        report.append("")

        # ============ 策略績效排名表 ============
        report.append("=" * 120)
        report.append("【日線策略績效排名表】(按 Sharpe Ratio 排序)")
        report.append("=" * 120)
        report.append("")

        # 構建 DataFrame
        results_data = []
        for strategy_name, metrics in self.results.items():
            results_data.append({
                '策略名稱': strategy_name,
                '總收益(%)': metrics['Total Return (%)'],
                '調整收益(%)': metrics['Adjusted Return (%)'],
                'Sharpe比': metrics['Sharpe Ratio'],
                '最大回撤(%)': metrics['Max Drawdown (%)'],
                '交易次數': metrics['Trades'],
                '勝率(%)': metrics['Win Rate (%)'],
                '最終資金': f"¥{metrics['Final Value']:,.0f}"
            })

        df_results = pd.DataFrame(results_data).sort_values('Sharpe比', ascending=False).reset_index(drop=True)
        df_results.index = df_results.index + 1

        report.append(df_results.to_string())
        report.append("")
        report.append("")

        # ============ 市場環境分析 ============
        report.append("=" * 120)
        report.append("【市場環境分析】")
        report.append("=" * 120)
        report.append("")

        # 計算各年度的市場表現
        market_yearly = {}
        for year in sorted(self.annual_results[list(self.annual_results.keys())[0]].keys()):
            year_data = self.df_daily[self.df_daily['Date'].dt.year == year]
            if len(year_data) > 0:
                year_start = year_data['Close'].iloc[0]
                year_end = year_data['Close'].iloc[-1]
                year_return = (year_end - year_start) / year_start * 100

                # 計算年度波動率
                year_returns = year_data['Close'].pct_change().dropna()
                year_volatility = year_returns.std() * np.sqrt(252) * 100

                market_yearly[year] = {
                    'Return': year_return,
                    'Volatility': year_volatility,
                    'Start': year_start,
                    'End': year_end
                }

        report.append("年度市場表現:")
        report.append("")
        for year in sorted(market_yearly.keys()):
            m = market_yearly[year]
            market_type = "牛市" if m['Return'] > 0 else "熊市"
            report.append(f"  {year}年 ({market_type:3s}): "
                         f"開盤{m['Start']:.0f} → 收盤{m['End']:.0f} | "
                         f"年度漲跌{m['Return']:+.2f}% | "
                         f"波動率{m['Volatility']:.2f}%")
        report.append("")
        report.append("")

        # ============ 分年表現詳表 ============
        report.append("=" * 120)
        report.append("【各策略年度表現對比表】")
        report.append("=" * 120)
        report.append("")

        years = sorted(self.annual_results[list(self.annual_results.keys())[0]].keys())
        for year in years:
            report.append(f"\n【{year}年表現】")
            report.append("-" * 80)

            year_data = []
            for strategy_name, annual_results in self.annual_results.items():
                if year in annual_results:
                    metrics = annual_results[year]
                    year_data.append({
                        '策略': strategy_name,
                        '收益(%)': metrics['Return (%)'],
                        'Sharpe': metrics['Sharpe'],
                        '交易次': metrics['Trades'],
                        '勝率(%)': metrics['Win Rate (%)']
                    })

            if year_data:
                df_year = pd.DataFrame(year_data).sort_values('Sharpe', ascending=False).reset_index(drop=True)
                df_year.index = df_year.index + 1
                report.append(df_year.to_string())
            else:
                report.append("  (數據不足)")
            report.append("")

        # ============ 最佳策略推薦 ============
        report.append("")
        report.append("=" * 120)
        report.append("【最佳策略推薦】")
        report.append("=" * 120)
        report.append("")

        best_sharpe = max(self.results.items(), key=lambda x: x[1]['Sharpe Ratio'])
        best_return = max(self.results.items(), key=lambda x: x[1]['Total Return (%)'])
        best_adj_return = max(self.results.items(), key=lambda x: x[1]['Adjusted Return (%)'])
        best_win_rate = max(self.results.items(), key=lambda x: x[1]['Win Rate (%)'])

        report.append(f"最佳 Sharpe 比: {best_sharpe[0]} ({best_sharpe[1]['Sharpe Ratio']})")
        report.append(f"最高總收益: {best_return[0]} ({best_return[1]['Total Return (%)']}%)")
        report.append(f"最高調整收益: {best_adj_return[0]} ({best_adj_return[1]['Adjusted Return (%)']}%)")
        report.append(f"最高勝率: {best_win_rate[0]} ({best_win_rate[1]['Win Rate (%)']}%)")
        report.append("")

        report.append("說明:")
        report.append("  - Sharpe 比越高，代表每單位風險的報酬越高，綜合風險調整績效最優")
        report.append("  - 調整收益已扣除換倉成本 ¥{:,.0f}".format(self.rollover_cost_info['total_cost']))
        report.append("  - 勝率反映策略的一致性，但不一定等於最高收益")
        report.append("")

        # ============ 結論 ============
        report.append("=" * 120)
        report.append("【結論與建議】")
        report.append("=" * 120)
        report.append("")

        report.append("1. 策略適用市場環境:")
        report.append("   - 趨勢型策略 (SMA、MACD、SuperTrend) 在牛市表現較好")
        report.append("   - 均值回歸策略 (均值回歸、RSI) 在振盪市表現較好")
        report.append("   - 多指標組合策略兼具穩定性和適應性")
        report.append("")

        report.append("2. 風險管理:")
        report.append(f"   - 換倉成本對績效有影響，建議選擇交易次數較少的策略")
        report.append("   - 注意最大回撤，控制風險敞口")
        report.append("")

        report.append("3. 後續優化方向:")
        report.append("   - 可加入止損/止盈機制控制單筆損失")
        report.append("   - 可根據市場環境動態調整策略組合權重")
        report.append("   - 考慮融合多策略集成方法提升穩定性")
        report.append("")

        # ============ 尾部 ============
        report.append("=" * 120)
        report.append(f"報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 120)

        report_text = "\n".join(report)

        # 保存報告
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)

        logger.info(f"\n✓ 報告已保存: {output_file}")

        # 保存 JSON 結果
        if json_output_file:
            json_results = {}
            for strategy_name, metrics in self.results.items():
                # 移除無法序列化的部分
                clean_metrics = {
                    'Total Return (%)': float(metrics['Total Return (%)']),
                    'Adjusted Return (%)': float(metrics['Adjusted Return (%)']),
                    'Sharpe Ratio': float(metrics['Sharpe Ratio']),
                    'Max Drawdown (%)': float(metrics['Max Drawdown (%)']),
                    'Win Rate (%)': float(metrics['Win Rate (%)']),
                    'Trades': int(metrics['Trades']),
                    'Final Value': float(metrics['Final Value'])
                }
                json_results[strategy_name] = clean_metrics

            # 清理年度結果，轉換所有 numpy 類型
            clean_annual_results = {}
            for strat, annual_results in self.annual_results.items():
                clean_annual_results[strat] = {}
                for year, metrics in annual_results.items():
                    clean_annual_results[strat][str(year)] = {
                        'Return (%)': float(metrics['Return (%)']),
                        'Sharpe': float(metrics['Sharpe']),
                        'Trades': int(metrics['Trades']),
                        'Win Rate (%)': float(metrics['Win Rate (%)']),
                        'Final Value': float(metrics['Final Value'])
                    }

            Path(json_output_file).parent.mkdir(parents=True, exist_ok=True)
            with open(json_output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'period': {
                        'start': str(self.df_daily['Date'].min()),
                        'end': str(self.df_daily['Date'].max())
                    },
                    'data_points': int(len(self.df_daily)),
                    'initial_capital': int(self.initial_capital),
                    'rollover_info': {
                        'num_rollovers': int(self.rollover_cost_info['num_rollovers']),
                        'cost_per_roll': int(self.rollover_cost_info['cost_per_roll']),
                        'total_cost': int(self.rollover_cost_info['total_cost'])
                    },
                    'strategies': json_results,
                    'annual_results': clean_annual_results
                }, f, ensure_ascii=False, indent=2)

            logger.info(f"✓ JSON 結果已保存: {json_output_file}")

        return report_text


def main():
    """主程序"""
    logger.info("\n開始加載數據...")

    # 加載數據
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_full_2019_2026.csv'
    df = pd.read_csv(data_file)

    logger.info(f"數據已加載: {len(df)} 行")
    logger.info(f"時間範圍: {df['Date'].min()} ~ {df['Date'].max()}")
    logger.info(f"欄位: {', '.join(df.columns.tolist())}")
    logger.info("")

    # 初始化回測引擎
    engine = BacktestEngine(
        df_daily=df,
        initial_capital=1_000_000,
        contract_size=200
    )

    # 執行回測
    logger.info("開始執行回測...")
    engine.run_all_strategies()

    # 生成報告
    output_file = '/home/tom/TX_Quantitative_Trading/reports/daily_backtest_full_2019_2026.md'
    json_output_file = '/home/tom/TX_Quantitative_Trading/data/daily_backtest_full_results.json'

    engine.generate_report(output_file, json_output_file)

    logger.info("\n" + "=" * 100)
    logger.info("✅ 回測完成！所有文件已生成")
    logger.info("=" * 100)


if __name__ == "__main__":
    main()
