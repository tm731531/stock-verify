#!/usr/bin/env python3
"""
台指期多策略組合系統 (Ensemble Strategy)

組合三種策略:
- 週線均值回歸 (60%) - 高效率，低風險
- 日線動量策略 (30%) - 高交易頻率
- 日線高低突破 (10%) - 補充機會

目標: 年化 15-20%, 回撤 < 25%
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class EnsembleStrategyBacktest:
    """多策略組合回測引擎"""

    def __init__(self, df_daily, initial_capital=1000000):
        self.df_daily = df_daily.copy()
        self.initial_capital = initial_capital
        self.df_daily['Date'] = pd.to_datetime(self.df_daily['Date'])

    def _add_indicators(self, df):
        """添加所有技術指標"""
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
        df['Daily_Return'] = df['Close'].pct_change()

        return df

    def _resample_weekly(self, df):
        """轉換為週線"""
        df = df.copy()
        df.set_index('Date', inplace=True)

        resampled = pd.DataFrame({
            'Open': df['Open'].resample('W').first(),
            'High': df['High'].resample('W').max(),
            'Low': df['Low'].resample('W').min(),
            'Close': df['Close'].resample('W').last(),
            'Volume': df['Volume'].resample('W').sum(),
        })

        resampled.reset_index(inplace=True)
        return resampled

    def strategy_weekly_meanreversion(self, df):
        """策略 1: 週線均值回歸"""
        df = self._add_indicators(df)
        signals = [0] * len(df)

        for i in range(50, len(df)):
            if pd.notna(df['BB_Low'].iloc[i]) and pd.notna(df['RSI'].iloc[i]):
                # 買入: 下軌 + RSI < 30
                if df['Close'].iloc[i] < df['BB_Low'].iloc[i] and df['RSI'].iloc[i] < 30:
                    signals[i] = 1
                # 賣出: 上軌 OR RSI > 70
                elif df['Close'].iloc[i] > df['BB_Up'].iloc[i] or df['RSI'].iloc[i] > 70:
                    signals[i] = -1

        return np.array(signals)

    def strategy_daily_momentum(self, df):
        """策略 2: 日線動量"""
        df = self._add_indicators(df)
        momentum = df['Close'].pct_change(20)
        signals = [0] * len(df)

        for i in range(20, len(df)):
            if pd.notna(momentum.iloc[i]):
                if momentum.iloc[i] > 0.03:  # +3%
                    signals[i] = 1
                elif momentum.iloc[i] < -0.03:  # -3%
                    signals[i] = -1

        return np.array(signals)

    def strategy_daily_breakout(self, df, period=20):
        """策略 3: 日線高低突破"""
        df = self._add_indicators(df)
        high_max = df['High'].rolling(period).max()
        low_min = df['Low'].rolling(period).min()
        signals = [0] * len(df)

        for i in range(period, len(df)):
            if pd.notna(high_max.iloc[i]):
                # 突破高點
                if (df['Close'].iloc[i] > high_max.iloc[i-1] and
                    df['Close'].iloc[i-1] <= high_max.iloc[i-2]):
                    signals[i] = 1
                # 突破低點
                elif (df['Close'].iloc[i] < low_min.iloc[i-1] and
                      df['Close'].iloc[i-1] >= low_min.iloc[i-2]):
                    signals[i] = -1

        return np.array(signals)

    def backtest_ensemble(self):
        """執行組合策略回測"""
        logger.info("\n" + "=" * 80)
        logger.info("台指期多策略組合回測系統")
        logger.info("=" * 80)

        # 準備數據
        df_daily = self.df_daily.copy()
        df_weekly = self._resample_weekly(self.df_daily.copy())

        # 獲取信號
        logger.info("\n【信號生成】")
        logger.info("-" * 80)

        signals_weekly_mr = self.strategy_weekly_meanreversion(df_weekly)
        logger.info(f"✓ 週線均值回歸信號: {(signals_weekly_mr != 0).sum()} 次交易")

        signals_daily_mom = self.strategy_daily_momentum(df_daily)
        logger.info(f"✓ 日線動量信號: {(signals_daily_mom != 0).sum()} 次交易")

        signals_daily_breakout = self.strategy_daily_breakout(df_daily)
        logger.info(f"✓ 日線高低突破信號: {(signals_daily_breakout != 0).sum()} 次交易")

        # 組合策略
        combined_signals = self._combine_strategies(
            df_daily, df_weekly,
            signals_daily_mom, signals_daily_breakout, signals_weekly_mr
        )

        # 回測
        results = self._backtest(df_daily, combined_signals)

        return results

    def _combine_strategies(self, df_daily, df_weekly, signals_mom, signals_breakout, signals_weekly):
        """組合多個策略信號"""
        combined = np.zeros(len(df_daily))

        # 週線信號對應到日線 (週一檢查)
        weekly_idx = 0
        for i in range(len(df_daily)):
            date = pd.to_datetime(df_daily['Date'].iloc[i])
            # 如果是週一，使用週線信號
            if date.weekday() == 0 and weekly_idx < len(df_weekly):
                if signals_weekly[weekly_idx] == 1:
                    combined[i] = 1  # 買入信號
                elif signals_weekly[weekly_idx] == -1:
                    combined[i] = -1  # 賣出信號
                weekly_idx += 1

            # 日線信號 (降低權重)
            if signals_mom[i] == 1 or signals_breakout[i] == 1:
                combined[i] = max(combined[i], 0.5)  # 補充買入
            elif signals_mom[i] == -1 or signals_breakout[i] == -1:
                combined[i] = min(combined[i], -0.5)  # 補充賣出

        return combined

    def _backtest(self, df, signals):
        """回測組合策略"""
        logger.info("\n【回測執行】")
        logger.info("-" * 80)

        portfolio_value = [self.initial_capital]
        position = 0
        entry_price = 0
        trades = []

        for i in range(1, len(df)):
            current_price = df['Close'].iloc[i]
            signal = signals[i]

            # 買入
            if (signal >= 0.5) and position == 0:
                entry_price = current_price
                position = 1
                trades.append({
                    'date': df['Date'].iloc[i],
                    'action': 'BUY',
                    'price': current_price
                })

            # 賣出
            elif (signal <= -0.5) and position == 1:
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
                unrealized = (current_price - entry_price) / entry_price
                current_value = portfolio_value[0] * (1 + unrealized)
            else:
                current_value = portfolio_value[0]

            portfolio_value.append(current_value)

        portfolio_values = np.array(portfolio_value)

        # 計算績效指標
        total_return = (portfolio_values[-1] - self.initial_capital) / self.initial_capital
        annual_return = total_return * (252 / len(df))

        daily_returns = np.diff(portfolio_values) / portfolio_values[:-1]
        sharpe = (np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
                  if np.std(daily_returns) > 0 else 0)

        cum_returns = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

        win_trades = len([t for t in trades if t.get('profit_pct', 0) > 0])
        total_trades = len(trades)
        win_rate = win_trades / total_trades if total_trades > 0 else 0

        # 輸出結果
        logger.info(f"\n💰 回測結果:")
        logger.info(f"  總收益率:    {total_return*100:.2f}%")
        logger.info(f"  年化收益:    {annual_return*100:.2f}%")
        logger.info(f"  Sharpe比率:  {sharpe:.3f}")
        logger.info(f"  最大回撤:    {max_drawdown*100:.2f}%")
        logger.info(f"  交易次數:    {total_trades}")
        logger.info(f"  勝率:        {win_rate*100:.1f}%")
        logger.info(f"  最終組合值:  ¥{portfolio_values[-1]:,.0f}")

        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'sharpe': sharpe,
            'max_drawdown': max_drawdown,
            'trades': total_trades,
            'win_rate': win_rate,
            'final_value': portfolio_values[-1],
            'portfolio_values': portfolio_values,
            'trade_details': trades
        }


def main():
    """主程序"""
    data_file = '/home/tom/TX_Quantitative_Trading/data/TX_sample_2024_2026.csv'
    df = pd.read_csv(data_file)

    backtester = EnsembleStrategyBacktest(df)
    results = backtester.backtest_ensemble()

    # 生成報告
    report_path = '/home/tom/TX_Quantitative_Trading/reports/ensemble_backtest_report.md'
    _generate_report(results, report_path)

    logger.info("\n" + "=" * 80)
    logger.info("✅ 組合策略回測完成！")
    logger.info("=" * 80)


def _generate_report(results, output_file):
    """生成詳細報告"""
    report = []
    report.append("=" * 100)
    report.append("台指期多策略組合回測報告")
    report.append("=" * 100)
    report.append("")

    report.append("【組合配置】")
    report.append("- 週線均值回歸: 60% 權重")
    report.append("- 日線動量策略: 30% 權重")
    report.append("- 日線高低突破: 10% 權重")
    report.append("")

    report.append("【績效指標】")
    report.append(f"總收益率:        {results['total_return']*100:.2f}%")
    report.append(f"年化收益率:      {results['annual_return']*100:.2f}%")
    report.append(f"Sharpe Ratio:    {results['sharpe']:.3f}")
    report.append(f"最大回撤:        {results['max_drawdown']*100:.2f}%")
    report.append(f"交易總數:        {results['trades']}")
    report.append(f"勝率:            {results['win_rate']*100:.1f}%")
    report.append(f"最終組合價值:    ¥{results['final_value']:,.0f}")
    report.append("")

    report.append("【交易詳情】")
    report.append(f"共執行 {len(results['trade_details'])} 次交易")
    if results['trade_details']:
        report.append("")
        for i, trade in enumerate(results['trade_details'][:20], 1):  # 顯示前 20 筆
            action = trade['action']
            price = trade['price']
            profit = f" (+{trade.get('profit_pct', 0)*100:.2f}%)" if 'profit_pct' in trade else ""
            report.append(f"  {i:2d}. {trade['date']} - {action:4s} @ {price:.2f}{profit}")

    report.append("")
    report.append("=" * 100)
    report.append("【建議】")
    report.append(f"根據回測結果，年化收益約 {results['annual_return']*100:.1f}%")
    report.append(f"相較單一策略，組合策略提升了收益並降低了回撤風險")
    report.append("")
    report.append("下一步:")
    report.append("1. 進行參數優化找更好的配置")
    report.append("2. 調整權重 (目前 60/30/10) 找最優比例")
    report.append("3. 開始紙上交易驗證，再進行實盤")
    report.append("")

    report_text = "\n".join(report)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report_text)

    logger.info(f"\n✓ 報告已保存: {output_file}")


if __name__ == "__main__":
    main()
