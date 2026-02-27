#!/usr/bin/env python3
"""
Backtest SMA Golden Cross Strategy
測試簡單的 SMA 黃金交叉策略 - 應該更乾淨、更可靠
"""

import json
import pandas as pd
import numpy as np
from strategies.sma_crossover_006208 import SMAcrossoverStrategy
from backtests.backtest_engine import BacktestEngine


def backtest_sma_crossover():
    """運行 SMA 黃金交叉策略回測"""

    print("=" * 100)
    print("SMA GOLDEN CROSS STRATEGY (20/50)")
    print("簡單 SMA 黃金交叉策略")
    print("=" * 100)

    # 加載數據
    df = pd.read_csv('data/006208_historical.csv', index_col='Date', parse_dates=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

    print(f"\n📊 回測期間: {df.index[0].date()} → {df.index[-1].date()}")
    print(f"📊 總交易日數: {len(df)}")
    print(f"💰 初始價格: ${df['Close'].iloc[0]:.2f}")
    print(f"💰 最終價格: ${df['Close'].iloc[-1]:.2f}")
    print(f"📈 市場總收益: {((df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1) * 100:+.2f}%")

    # 參數設定
    PARAMS = {
        'sma_short': 20,
        'sma_long': 50,
        'stop_loss_pct': 0.05,  # -5% 快速停損
        'max_hold_days': 60
    }

    print(f"\n{'-' * 100}")
    print("STRATEGY PARAMETERS / 策略參數")
    print(f"{'-' * 100}")
    print(f"SMA Short Period:      {PARAMS['sma_short']} 日")
    print(f"SMA Long Period:       {PARAMS['sma_long']} 日")
    print(f"Entry Signal:          20日 SMA 上穿 50日 SMA（黃金交叉）")
    print(f"Exit Signal #1:        20日 SMA 下穿 50日 SMA（死亡交叉）")
    print(f"Exit Signal #2:        Stop Loss -{PARAMS['stop_loss_pct']:.0%}")
    print(f"Max Hold Days:         {PARAMS['max_hold_days']} 天")

    # 創建策略和回測引擎
    strategy = SMAcrossoverStrategy(
        sma_short=PARAMS['sma_short'],
        sma_long=PARAMS['sma_long'],
        stop_loss_pct=PARAMS['stop_loss_pct'],
        max_hold_days=PARAMS['max_hold_days']
    )

    backtest = BacktestEngine(
        strategy=strategy,
        initial_capital=1000000,
        commission_rate=0.0003
    )

    df = strategy.calculate_indicators(df)
    backtest.load_data(df)
    trades = backtest.simulate()
    stats = backtest._calculate_performance_stats()

    # 全期間績效
    print(f"\n{'-' * 100}")
    print("OVERALL PERFORMANCE / 全期間績效 (2020-2026)")
    print(f"{'-' * 100}")

    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl < 0)

    print(f"\n📊 交易統計:")
    print(f"  總交易數:             {len(trades)}")
    print(f"  獲利交易:             {wins}")
    print(f"  虧損交易:             {losses}")
    print(f"  勝率:                 {stats['win_rate']:.1f}%")
    print(f"  利潤因子:             {stats['profit_factor']:.2f}")

    print(f"\n💰 損益分析:")
    print(f"  總損益:               ${stats['total_pnl']:+,.2f}")
    print(f"  平均獲利:             ${stats['avg_win']:+,.2f}")
    print(f"  平均虧損:             ${stats['avg_loss']:+,.2f}")
    if abs(stats['avg_loss']) > 0 and losses > 0:
        print(f"  獲利/虧損比:          {abs(stats['avg_win']) / abs(stats['avg_loss']):.2f}x")

    print(f"\n⚠️  風險指標:")
    print(f"  最大回撤:             {stats['max_drawdown_pct']:.2f}%")

    initial_capital = 1000000
    final_capital = backtest.current_cash
    total_return = ((final_capital - initial_capital) / initial_capital) * 100
    print(f"\n💵 資本變化:")
    print(f"  初始資本:             ${initial_capital:,.0f}")
    print(f"  最終資本:             ${final_capital:,.2f}")
    print(f"  總報酬率:             {total_return:+.3f}%")

    # 分析各時期的性能
    print(f"\n{'-' * 100}")
    print("PERIOD-BY-PERIOD ANALYSIS / 各時期分析")
    print(f"{'-' * 100}")

    periods = {
        '2020': ('2020-01-01', '2020-12-31'),
        '2021': ('2021-01-01', '2021-12-31'),
        '2022 (Crash Year)': ('2022-01-01', '2022-12-31'),
        '2023': ('2023-01-01', '2023-12-31'),
        '2024': ('2024-01-01', '2024-12-31'),
        '2025': ('2025-01-01', '2025-12-31'),
    }

    for period_name, (start, end) in periods.items():
        period_data = df.loc[start:end]
        if len(period_data) > 0:
            period_trades = [t for t in trades if start <= t.entry_date.strftime('%Y-%m-%d') <= end]
            market_start = period_data['Close'].iloc[0]
            market_end = period_data['Close'].iloc[-1]
            market_return = ((market_end / market_start) - 1) * 100

            period_pnl = sum(t.pnl for t in period_trades)
            period_wins = sum(1 for t in period_trades if t.pnl > 0)

            print(f"\n{period_name}:")
            print(f"  市場回報:             {market_return:+.1f}%")
            print(f"  策略交易:             {len(period_trades)} 筆")
            if len(period_trades) > 0:
                print(f"    - 獲利:              {period_wins}/{len(period_trades)}")
                print(f"    - 總損益:            ${period_pnl:+,.2f}")

    # 出場原因分析
    print(f"\n{'-' * 100}")
    print("EXIT SIGNAL PERFORMANCE / 出場訊號表現分析")
    print(f"{'-' * 100}")

    exit_summary = {}
    for trade in trades:
        reason = trade.exit_reason
        if reason not in exit_summary:
            exit_summary[reason] = {'count': 0, 'pnl': 0, 'wins': 0}
        exit_summary[reason]['count'] += 1
        exit_summary[reason]['pnl'] += trade.pnl
        if trade.pnl > 0:
            exit_summary[reason]['wins'] += 1

    for reason in sorted(exit_summary.keys()):
        data = exit_summary[reason]
        wr = (data['wins'] / data['count'] * 100) if data['count'] > 0 else 0
        print(f"\n{reason.upper()}:")
        print(f"  次數:                 {data['count']}")
        print(f"  勝率:                 {wr:.0f}%")
        print(f"  總損益:               ${data['pnl']:+,.2f}")
        print(f"  平均/筆:              ${data['pnl'] / data['count']:+,.2f}")

    # 詳細交易列表（最多顯示 20 筆）
    if len(trades) > 0:
        print(f"\n{'-' * 100}")
        print(f"DETAILED TRADES / 交易明細 (顯示前 20 筆)")
        print(f"{'-' * 100}")

        for i, trade in enumerate(trades[:20], 1):
            days_held = (trade.exit_date - trade.entry_date).days
            pnl_pct = (trade.pnl / trade.entry_price) * 100
            status = "✅ WIN" if trade.pnl > 0 else "❌ LOSS"

            print(f"\n{i}. {status}")
            print(f"   {trade.entry_date.date()} → {trade.exit_date.date()} ({days_held}d)")
            print(f"   進場: ${trade.entry_price:.2f} | 出場: ${trade.exit_price:.2f}")
            print(f"   損益: ${trade.pnl:+,.2f} ({pnl_pct:+.2f}%) | 原因: {trade.exit_reason}")

    # 策略驗證
    print(f"\n{'-' * 100}")
    print("STRATEGY VALIDATION / 策略驗收")
    print(f"{'-' * 100}")

    ready = True

    # 檢查條件 1: 利潤因子 > 1.5
    if stats['profit_factor'] > 1.5:
        print("✅ 利潤因子 > 1.5")
    else:
        print(f"⚠️  利潤因子 < 1.5 ({stats['profit_factor']:.2f})")

    # 檢查條件 2: 勝率 > 40%
    if stats['win_rate'] > 40:
        print("✅ 勝率 > 40%")
    else:
        print(f"⚠️  勝率 < 40% ({stats['win_rate']:.1f}%)")

    # 檢查條件 3: 總損益 > 0
    if stats['total_pnl'] > 0:
        print("✅ 總損益 > 0")
    else:
        print(f"⚠️  總損益 < 0 (${stats['total_pnl']:+,.2f})")

    # 檢查條件 4: 交易次數 >= 5
    if len(trades) >= 5:
        print(f"✅ 交易次數充足 ({len(trades)} 筆)")
    else:
        print(f"⚠️  交易次數較少 ({len(trades)} 筆)")

    # 檢查條件 5: 2022 年保護（虧損 < 20%）
    year_2022_trades = [t for t in trades if t.entry_date.year == 2022]
    year_2022_pnl = sum(t.pnl for t in year_2022_trades)
    year_2022_pct = (year_2022_pnl / 1000000) * 100

    print(f"\n🛡️  2022 年保護機制:")
    print(f"   2022 年交易: {len(year_2022_trades)} 筆")
    if len(year_2022_trades) > 0:
        print(f"   2022 年損益: ${year_2022_pnl:+,.2f} ({year_2022_pct:+.2f}%)")
        if year_2022_pct > -20:
            print("   ✅ 保護機制有效（虧損 < 20%）")
        else:
            print("   ⚠️  保護機制需要改進")
    else:
        print("   ℹ️  2022 年無交易（應該是好信號）")

    print(f"\n{'=' * 100}")
    if stats['total_pnl'] > 0:
        print("✨ 策略可以進行進一步優化!")
    elif stats['profit_factor'] > 1.0:
        print("⚠️  策略有潛力但需要優化")
    else:
        print("⚠️  策略需要重新考慮邏輯")
    print(f"{'=' * 100}\n")

    return trades, stats


if __name__ == '__main__':
    trades, stats = backtest_sma_crossover()
