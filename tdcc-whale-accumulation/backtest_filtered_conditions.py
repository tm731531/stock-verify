#!/usr/bin/env python3
"""
新篩選條件回測
============================================
條件：
1. 股價: 50-150 元
2. 散戶逃幅: -7% ~ -5%（4週內）
3. r400_chg: +0.3% ~ +1.0%（4週內大戶增加幅度）
4. 站上 MA20
5. 出場: -7% 停損 | +15% trailing | 90天到期

配置: 90天 + 3個持倉
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = './data/tdcc_holdings.db'

def load_data():
    conn = sqlite3.connect(DB_PATH)
    holdings = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    prices = pd.read_sql("SELECT * FROM daily_prices ORDER BY stock_code, date", conn)
    conn.close()
    return holdings, prices

def get_ma(prices_df, stock, date, period=20):
    """計算指定日期的 MA"""
    df = prices_df[prices_df['stock_code'] == stock].copy()
    df = df[df['date'] <= date].tail(period)
    if len(df) >= period:
        return df['close_price'].astype(float).mean()
    return None

def scan_backup_engine_filtered(holdings, prices, scan_date):
    """
    新版備位引擎掃描，使用優化的條件
    """
    scan_date = pd.to_datetime(scan_date)
    signals = []

    four_weeks_ago = scan_date - timedelta(days=28)

    unique_stocks = holdings['stock_code'].unique()

    for stock_code in unique_stocks:
        try:
            stock_holdings = holdings[holdings['stock_code'] == stock_code].copy()
            stock_holdings = stock_holdings[
                (stock_holdings['date'] >= four_weeks_ago) &
                (stock_holdings['date'] <= scan_date)
            ].sort_values('date')

            if len(stock_holdings) < 2:
                continue

            # 計算散戶逃幅
            first_holders = float(stock_holdings.iloc[0]['total_holders'] or 0)
            last_holders = float(stock_holdings.iloc[-1]['total_holders'] or 0)

            if first_holders <= 0:
                continue

            fled_pct = (last_holders - first_holders) / first_holders * 100

            # 條件1：散戶逃幅 -7% ~ -5%
            if fled_pct > -5.0 or fled_pct < -7.0:
                continue

            # 計算 r400_chg
            first_r400 = float(stock_holdings.iloc[0]['ratio_400_above'] or 0)
            last_r400 = float(stock_holdings.iloc[-1]['ratio_400_above'] or 0)
            r400_chg = last_r400 - first_r400

            # 條件2：r400_chg +0.3% ~ +1.0%（選擇性買進，非積極）
            if r400_chg < 0.3 or r400_chg > 1.0:
                continue

            # 取得掃描日的股價
            stock_prices = prices[prices['stock_code'] == stock_code].copy()
            stock_prices = stock_prices[stock_prices['date'] == scan_date]

            if len(stock_prices) == 0:
                continue

            close_price = float(stock_prices.iloc[0]['close_price'])

            # 條件3：股價 50-150 元
            if close_price < 50 or close_price > 150:
                continue

            # 條件4：站上 MA20
            ma20 = get_ma(prices, stock_code, scan_date, 20)
            if ma20 is None or close_price <= ma20:
                continue

            signals.append({
                'code': stock_code,
                'signal_date': scan_date.strftime('%Y%m%d'),
                'close_price': close_price,
                'ma20': ma20,
                'fled_pct': fled_pct,
                'r400_chg': r400_chg,
            })

        except:
            pass

    return signals

def backtest_filtered():
    """執行新條件的完整回測"""
    print("=" * 100)
    print("新篩選條件回測 - 90天 + 3個持倉")
    print("=" * 100)
    print()
    print("進場條件:")
    print("  ✓ 股價: 50-150 元")
    print("  ✓ 散戶逃幅: -7% ~ -5%（4週內）")
    print("  ✓ r400_chg: +0.3% ~ +1.0%（大戶選擇性買進）")
    print("  ✓ 站上 MA20")
    print()
    print("出場條件:")
    print("  • 停損: -7%")
    print("  • 追蹤停利: +15% 啟動，回落 10% 出場")
    print("  • 到期: 90 天曆日")
    print()

    holdings, prices = load_data()
    holdings['date'] = pd.to_datetime(holdings['date'])
    prices['date'] = pd.to_datetime(prices['date'])

    # 掃描日期範圍
    start_date = pd.to_datetime('2022-01-01')
    end_date = pd.to_datetime('2025-12-31')

    # 每週掃描一次
    trade_dates = sorted(prices['date'].unique())
    trade_dates = [d for d in trade_dates if start_date <= d <= end_date]

    # 生成所有訊號
    print(f"掃描期間: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    all_signals = []

    for i, date in enumerate(trade_dates):
        if i % 50 == 0:
            print(f"  掃描中... {i}/{len(trade_dates)}", end='\r')
        signals = scan_backup_engine_filtered(holdings, prices, date)
        all_signals.extend(signals)

    print(f"  掃描完成！共找到 {len(all_signals)} 個訊號")
    print()

    if not all_signals:
        print("❌ 沒有找到符合條件的訊號")
        return None

    # 轉換為 DataFrame
    signals_df = pd.DataFrame(all_signals)
    signals_df['signal_date'] = pd.to_datetime(signals_df['signal_date'], format='%Y%m%d')
    signals_df = signals_df.sort_values('signal_date')

    print(f"訊號統計:")
    print(f"  平均股價: NT${signals_df['close_price'].mean():.0f}")
    print(f"  股價範圍: NT${signals_df['close_price'].min():.0f} ~ NT${signals_df['close_price'].max():.0f}")
    print(f"  平均散戶逃幅: {signals_df['fled_pct'].mean():.2f}%")
    print(f"  平均 r400_chg: {signals_df['r400_chg'].mean():.3f}%")
    print()

    # 執行回測
    positions = []  # 當前持倉
    trades = []     # 已平倉交易
    capital = 500_000
    per_position = 125_000
    max_positions = 3

    for idx, sig in signals_df.iterrows():
        sig_date = sig['signal_date']
        sig_code = sig['code']

        # 檢查是否已有此股票的持倉
        if any(p['code'] == sig_code for p in positions):
            continue

        # 檢查部位數量
        if len(positions) >= max_positions:
            continue

        # 進場5日內找到進場價
        entry_price = None
        entry_date = None

        stock_prices = prices[prices['stock_code'] == sig_code].copy()
        for days_after in range(1, 6):
            entry_search_date = sig_date + timedelta(days=days_after)
            price_on_date = stock_prices[stock_prices['date'] == entry_search_date]

            if len(price_on_date) > 0:
                entry_price = float(price_on_date.iloc[0]['close_price'])
                entry_date = entry_search_date
                break

        if entry_price is None:
            continue

        # 計算股份數
        shares = int(per_position / entry_price)

        # 建立持倉
        positions.append({
            'code': sig_code,
            'signal_date': sig_date,
            'entry_date': entry_date,
            'entry_price': entry_price,
            'shares': shares,
            'cost': entry_price * shares,
            'peak_price': entry_price,
            'days_held': 0,
            'tp_activated': False,
            'highest_pnl': 0,
        })

    # 模擬持倉演進
    print("模擬持倉演進中...")

    for current_date in trade_dates:
        # 更新持倉
        positions_to_remove = []

        for i, pos in enumerate(positions):
            stock = pos['code']
            entry_date = pos['entry_date']
            days_held = (current_date - entry_date).days

            # 取得當日股價
            price_today = prices[
                (prices['stock_code'] == stock) &
                (prices['date'] == current_date)
            ]

            if len(price_today) == 0:
                continue

            close_price = float(price_today.iloc[0]['close_price'])
            pos['peak_price'] = max(pos['peak_price'], close_price)
            pos['days_held'] = days_held

            # 計算 PnL
            pnl_pct = (close_price - pos['entry_price']) / pos['entry_price'] * 100
            current_pnl = close_price * pos['shares'] - pos['cost']

            # 檢查出場條件
            should_exit = False
            exit_reason = None
            exit_price = close_price

            # 條件1：停損 -7%
            if pnl_pct <= -7.0:
                should_exit = True
                exit_reason = '停損'
                exit_price = pos['entry_price'] * 0.93

            # 條件2：追蹤停利 (+15% 啟動，回落 10%)
            elif pnl_pct >= 15.0:
                pos['tp_activated'] = True
                pos['highest_pnl'] = max(pos['highest_pnl'], pnl_pct)

            if pos['tp_activated'] and (pos['highest_pnl'] - pnl_pct) >= 10.0:
                should_exit = True
                exit_reason = '追蹤停利'

            # 條件3：90天到期
            elif days_held >= 90:
                should_exit = True
                exit_reason = '到期'

            # 執行出場
            if should_exit:
                profit = close_price * pos['shares'] - pos['cost']
                profit_pct = (close_price - pos['entry_price']) / pos['entry_price'] * 100

                trades.append({
                    'code': stock,
                    'entry_date': pos['entry_date'].strftime('%Y%m%d'),
                    'exit_date': current_date.strftime('%Y%m%d'),
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'shares': pos['shares'],
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'days_held': days_held,
                    'exit_reason': exit_reason,
                })

                positions_to_remove.append(i)

        # 移除已平倉持倉
        for i in sorted(positions_to_remove, reverse=True):
            positions.pop(i)

    # 統計結果
    print()
    print("=" * 100)
    print("回測結果")
    print("=" * 100)
    print()

    if not trades:
        print("❌ 沒有交易")
        return None

    trades_df = pd.DataFrame(trades)
    trades_df['profit_pct'] = pd.to_numeric(trades_df['profit_pct'], errors='coerce')
    trades_df['profit'] = pd.to_numeric(trades_df['profit'], errors='coerce')

    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['profit'] > 0])
    losing_trades = len(trades_df[trades_df['profit'] <= 0])
    win_rate = winning_trades / total_trades * 100

    total_profit = trades_df['profit'].sum()
    avg_profit_per_trade = trades_df['profit'].mean()

    print(f"交易統計:")
    print(f"  總交易數: {total_trades}")
    print(f"  獲利筆數: {winning_trades} ({win_rate:.1f}%)")
    print(f"  虧損筆數: {losing_trades}")
    print()
    print(f"利潤統計:")
    print(f"  合計利潤: NT${total_profit:,.0f}")
    print(f"  平均每筆: NT${avg_profit_per_trade:,.0f}")
    print(f"  平均報酬: {trades_df['profit_pct'].mean():.2f}%")
    print()

    # 按出場原因分類
    print(f"出場原因分布:")
    for reason in trades_df['exit_reason'].unique():
        count = len(trades_df[trades_df['exit_reason'] == reason])
        trades_by_reason = trades_df[trades_df['exit_reason'] == reason]
        wr = len(trades_by_reason[trades_by_reason['profit'] > 0]) / count * 100
        avg_pnl = trades_by_reason['profit_pct'].mean()
        print(f"  {reason:6s}: {count:3d} 筆 | 勝率 {wr:5.1f}% | 平均 {avg_pnl:+6.2f}%")

    print()
    print("=" * 100)
    print("前10個交易記錄")
    print("=" * 100)
    print(trades_df.head(10)[['code', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'profit_pct', 'exit_reason']].to_string(index=False))

    # 保存結果
    output_file = '/tmp/trading_reports/新篩選條件_90天+3個持倉.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 詳細結果已保存: {output_file}")

    return {
        'trades': trades_df,
        'total_profit': total_profit,
        'win_rate': win_rate,
        'avg_profit': avg_profit_per_trade,
        'total_trades': total_trades
    }

if __name__ == '__main__':
    result = backtest_filtered()
