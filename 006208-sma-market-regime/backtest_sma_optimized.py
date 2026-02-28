#!/usr/bin/env python3
"""
SMA20/50 最優化回測
- 使用最高價進場（更保守估計）
- 優化的格式輸出
"""

import pandas as pd
import numpy as np

def backtest_sma_with_high_entry(csv_path: str) -> dict:
    """使用最高價進場的 SMA20/50 回測"""

    df = pd.read_csv(csv_path, index_col='Date', parse_dates=True)
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()

    df['TR'] = np.maximum(
        df['High'] - df['Low'],
        np.maximum(
            abs(df['High'] - df['Close'].shift(1)),
            abs(df['Low'] - df['Close'].shift(1))
        )
    )
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df['ATR_MA'] = df['ATR'].rolling(window=20).mean()
    df['Daily_Return'] = df['Close'].pct_change()

    initial_capital = 500000
    cash = initial_capital
    position_value = 0
    shares_held = 0
    entry_price = 0
    entry_date = None
    trades = []

    for idx, row in df.iterrows():
        date = idx
        high = row['High']
        close = row['Close']
        sma20 = row['SMA_20']
        sma50 = row['SMA_50']
        atr = row['ATR']
        atr_ma = row['ATR_MA']
        daily_ret = row['Daily_Return']

        if pd.isna(sma20) or pd.isna(sma50):
            continue

        # 出場邏輯
        if shares_held > 0:
            current_value = shares_held * close

            # 警訊止損
            if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
                if atr > atr_ma * 1.5 and daily_ret < -0.03:
                    realized_pnl = current_value - position_value
                    trades.append({
                        'date': date,
                        'type': 'EXIT_ALERT',
                        'entry_price': entry_price,
                        'exit_price': close,
                        'price': close,
                        'sma20': sma20,
                        'sma50': sma50,
                        'reason': f'警訊止損',
                        'pnl': realized_pnl,
                    })
                    cash += current_value
                    shares_held = 0
                    position_value = 0
                    entry_price = 0
                    entry_date = None
                    continue

            # 死亡交叉
            if sma20 < sma50 and shares_held > 0:
                realized_pnl = current_value - position_value
                trades.append({
                    'date': date,
                    'type': 'EXIT_CROSS',
                    'entry_price': entry_price,
                    'exit_price': close,
                    'price': close,
                    'sma20': sma20,
                    'sma50': sma50,
                    'reason': f'死亡交叉',
                    'pnl': realized_pnl,
                })
                cash += current_value
                shares_held = 0
                position_value = 0
                entry_price = 0
                entry_date = None

        # 進場邏輯 - 使用最高價
        if shares_held == 0 and cash >= 100000 + 200000:
            if sma20 > sma50:
                if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
                    if atr <= atr_ma * 1.3:
                        # 用最高價進場
                        entry_price = high
                        entry_date = date
                        shares_bought = 100000 / high
                        shares_held = shares_bought
                        position_value = 100000
                        cash -= 100000

                        trades.append({
                            'date': date,
                            'type': 'ENTRY',
                            'entry_price': entry_price,
                            'exit_price': 0,
                            'price': high,
                            'sma20': sma20,
                            'sma50': sma50,
                            'reason': f'進場',
                            'pnl': 0,
                        })

        # 加倀邏輯 - 使用最高價
        elif shares_held > 0 and sma20 > sma50 and position_value < 300000:
            if cash >= 100000 + 200000:
                days_held = (date - entry_date).days
                if days_held >= 5:
                    # 用最高價加倀
                    add_price = high
                    add_shares = 100000 / add_price
                    shares_held += add_shares
                    position_value += 100000
                    cash -= 100000

                    trades.append({
                        'date': date,
                        'type': 'ADD',
                        'entry_price': add_price,
                        'exit_price': 0,
                        'price': high,
                        'sma20': sma20,
                        'sma50': sma50,
                        'reason': f'加倀',
                        'pnl': 0,
                    })

    final_value = cash + (shares_held * df['Close'].iloc[-1])
    exit_trades = [t for t in trades if 'EXIT' in t['type']]
    total_realized = sum([t['pnl'] for t in exit_trades])

    return {
        'trades': trades,
        'final_cash': cash,
        'final_position_value': position_value,
        'final_total_value': final_value,
        'total_realized_pnl': total_realized,
        'total_return_pct': ((final_value - initial_capital) / initial_capital) * 100,
    }


if __name__ == '__main__':
    csv_path = 'data/006208_historical.csv'
    result = backtest_sma_with_high_entry(csv_path)

    print("\n" + "="*150)
    print("📊 SMA20/50 最優化回測（使用最高價進場）")
    print("="*150)

    # 統計
    entries = len([t for t in result['trades'] if t['type'] == 'ENTRY'])
    adds = len([t for t in result['trades'] if t['type'] == 'ADD'])
    exits = len([t for t in result['trades'] if 'EXIT' in t['type']])

    print(f"\n📈 績效統計")
    print(f"{'─'*50}")
    print(f"進場：{entries} 次")
    print(f"加倀：{adds} 次")
    print(f"出場：{exits} 次")
    print(f"\n已實現獲利：${result['total_realized_pnl']:+,.0f}")
    print(f"當前現金：${result['final_cash']:,.0f}")
    print(f"當前倉位：${result['final_position_value']:,.0f}")
    print(f"總資產：${result['final_total_value']:,.0f}")
    print(f"總報酬率：{result['total_return_pct']:+.2f}%")

    # 出場績效
    exit_trades = [t for t in result['trades'] if 'EXIT' in t['type']]
    if exit_trades:
        exit_pnls = [t['pnl'] for t in exit_trades]
        winning = len([p for p in exit_pnls if p > 0])
        print(f"\n📊 出場績效")
        print(f"{'─'*50}")
        print(f"勝率：{winning}/{len(exit_pnls)} ({winning/len(exit_pnls)*100:.0f}%)")
        print(f"平均獲利：${np.mean(exit_pnls):+,.0f}")
        print(f"最大獲利：${np.max(exit_pnls):+,.0f}")
        print(f"最大虧損：${np.min(exit_pnls):+,.0f}")

    # 詳細交易記錄
    print(f"\n" + "="*150)
    print("📋 交易詳細記錄（前 40 次）")
    print("="*150)

    print(f"\n{'日期':<12} {'類型':<8} {'進價':<8} {'現價':<8} {'SMA20':<8} {'SMA50':<8} {'原因':<15} {'損益':<12}")
    print("─"*130)

    for i, trade in enumerate(result['trades'][:40]):
        date_str = trade['date'].strftime('%Y-%m-%d')
        trade_type = trade['type']
        entry = trade['entry_price']
        price = trade['price']
        sma20 = trade['sma20']
        sma50 = trade['sma50']
        reason = trade['reason']
        pnl_str = f"{trade['pnl']:+.0f}" if trade['pnl'] != 0 else "-"

        print(f"{date_str:<12} {trade_type:<8} ${entry:<7.2f} ${price:<7.2f} ${sma20:<7.2f} ${sma50:<7.2f} {reason:<15} {pnl_str:<12}")

    if len(result['trades']) > 40:
        print(f"\n... 共 {len(result['trades'])} 次交易")

    print("\n" + "="*150 + "\n")

