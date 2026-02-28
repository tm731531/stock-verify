#!/usr/bin/env python3
"""
比較不同 SMA 組合的回測績效
目標：找出最佳的進出場組合

配置：
- 單筆交易額：$100,000
- 倉位上限：$300,000 (最多 3 筆)
- 現金保留：$200,000+
- 出場邏輯：警訊止損 + 死亡交叉
"""

import pandas as pd
import numpy as np
from datetime import datetime

def backtest_sma_combination(csv_path: str, sma_fast: int, sma_slow: int, label: str = '') -> dict:
    """運行指定 SMA 組合的回測"""

    # 載入數據
    df = pd.read_csv(csv_path, index_col='Date', parse_dates=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

    # 計算指標
    df['SMA_FAST'] = df['Close'].rolling(window=sma_fast).mean()
    df['SMA_SLOW'] = df['Close'].rolling(window=sma_slow).mean()

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

    # 初始化
    initial_capital = 500000
    single_trade_amount = 100000
    max_position = 300000
    min_cash_buffer = 200000

    cash = initial_capital
    position_value = 0
    shares_held = 0
    entry_price = 0
    entry_date = None

    trades = []
    monthly_realized = {}

    # 回測迴圈
    for idx, row in df.iterrows():
        date = idx
        close = row['Close']
        sma_fast = row['SMA_FAST']
        sma_slow = row['SMA_SLOW']
        atr = row['ATR']
        atr_ma = row['ATR_MA']
        daily_ret = row['Daily_Return']

        # 檢查資料完整性
        if pd.isna(sma_fast) or pd.isna(sma_slow):
            continue

        month_key = date.strftime('%Y-%m')

        # ===== 出場檢查 =====
        if shares_held > 0:
            current_value = shares_held * close
            unrealized_pnl = current_value - position_value

            # 規則 1: 快速止損 (警訊 + 大跌)
            if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
                if atr > atr_ma * 1.5 and daily_ret < -0.03:
                    realized_pnl = current_value - position_value
                    cash += current_value
                    trades.append({
                        'date': date,
                        'type': 'exit_stop_loss',
                        'price': close,
                        'realized_pnl': realized_pnl,
                    })

                    if month_key not in monthly_realized:
                        monthly_realized[month_key] = 0
                    monthly_realized[month_key] += realized_pnl

                    shares_held = 0
                    position_value = 0
                    entry_price = 0
                    entry_date = None
                    continue

            # 規則 2: 死亡交叉快速全出
            if sma_fast < sma_slow and shares_held > 0:
                realized_pnl = current_value - position_value
                cash += current_value
                trades.append({
                    'date': date,
                    'type': 'exit_death_cross',
                    'price': close,
                    'realized_pnl': realized_pnl,
                })

                if month_key not in monthly_realized:
                    monthly_realized[month_key] = 0
                monthly_realized[month_key] += realized_pnl

                shares_held = 0
                position_value = 0
                entry_price = 0
                entry_date = None

        # ===== 進場檢查 =====
        if shares_held == 0 and cash >= single_trade_amount + min_cash_buffer:
            # 黃金交叉進場訊號
            if sma_fast > sma_slow:
                if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
                    if atr <= atr_ma * 1.3:
                        # 進場
                        entry_price = close
                        entry_date = date
                        shares_bought = single_trade_amount / close
                        shares_held = shares_bought
                        position_value = single_trade_amount
                        cash -= single_trade_amount

                        trades.append({
                            'date': date,
                            'type': 'entry',
                            'price': close,
                        })

        # ===== 加倀檢查 =====
        elif shares_held > 0 and sma_fast > sma_slow and position_value < max_position:
            if cash >= single_trade_amount + min_cash_buffer:
                # 檢查是否已持倉 5+ 天
                days_held = (date - entry_date).days
                if days_held >= 5:
                    # 加倒
                    add_shares = single_trade_amount / close
                    shares_held += add_shares
                    position_value += single_trade_amount
                    cash -= single_trade_amount

                    trades.append({
                        'date': date,
                        'type': 'add_position',
                        'price': close,
                    })

    # 計算統計
    final_value = cash + (shares_held * df['Close'].iloc[-1])
    total_realized = sum(monthly_realized.values())

    return {
        'sma_combo': label if label else f'SMA{sma_fast}/{sma_slow}',
        'trades': trades,
        'monthly_realized': monthly_realized,
        'initial_capital': initial_capital,
        'final_cash': cash,
        'final_position_value': position_value,
        'final_total_value': final_value,
        'total_realized_pnl': total_realized,
        'total_return_pct': ((final_value - initial_capital) / initial_capital) * 100,
        'realized_return_pct': (total_realized / initial_capital) * 100,
        'num_trades': len([t for t in trades if t['type'] == 'entry']),
        'num_exits': len([t for t in trades if 'exit' in t['type']]),
    }


# 執行回測
if __name__ == '__main__':
    csv_path = 'data/006208_historical.csv'

    # 定義要測試的 SMA 組合
    combinations = [
        (50, 200, 'SMA50/200'),    # 當前系統（保守）
        (20, 50, 'SMA20/50'),       # 中速反應
        (12, 26, 'SMA12/26'),       # MACD 式（快速）
        (10, 30, 'SMA10/30'),       # 介於中間
        (5, 20, 'SMA5/20'),         # 極快速反應
    ]

    results = []

    print("\n" + "="*150)
    print("📊 006208 SMA 組合對比回測 (2020-2026)")
    print("="*150)

    for fast, slow, label in combinations:
        print(f"🔄 測試 {label}...", end=' ')
        result = backtest_sma_combination(csv_path, fast, slow, label)
        results.append(result)
        print("✅ 完成")

    # 輸出對比表
    print("\n" + "="*150)
    print("📈 績效對比表")
    print("="*150 + "\n")

    print(f"{'SMA組合':<15} {'已實現':<15} {'現有現金':<15} {'持倉金額':<15} {'總資產':<15} {'總報酬':<12} {'實現報酬':<12} {'進場':<8} {'出場':<8}")
    print("-"*150)

    for result in results:
        combo = result['sma_combo']
        realized = result['total_realized_pnl']
        cash = result['final_cash']
        position = result['final_position_value']
        total = result['final_total_value']
        total_ret = result['total_return_pct']
        realized_ret = result['realized_return_pct']
        entries = result['num_trades']
        exits = result['num_exits']

        print(f"{combo:<15} ${realized:>13,.0f} ${cash:>13,.0f} ${position:>13,.0f} ${total:>13,.0f} {total_ret:>10.2f}% {realized_ret:>10.2f}% {entries:>7} {exits:>7}")

    # 找出最好的組合
    print("\n" + "="*150)
    print("🏆 排名")
    print("="*150 + "\n")

    # 按已實現現金排名
    print("【按已實現現金排名】")
    sorted_by_realized = sorted(results, key=lambda x: x['total_realized_pnl'], reverse=True)
    for i, result in enumerate(sorted_by_realized, 1):
        print(f"  {i}. {result['sma_combo']:<12} 已實現 ${result['total_realized_pnl']:>10,.0f} (報酬 {result['realized_return_pct']:>6.2f}%)")

    # 按總報酬排名
    print("\n【按總資產報酬排名】")
    sorted_by_total = sorted(results, key=lambda x: x['total_return_pct'], reverse=True)
    for i, result in enumerate(sorted_by_total, 1):
        print(f"  {i}. {result['sma_combo']:<12} 總資產 ${result['final_total_value']:>10,.0f} (報酬 {result['total_return_pct']:>6.2f}%)")

    # 按現金流排名
    print("\n【按現有現金排名】(流動性)")
    sorted_by_cash = sorted(results, key=lambda x: x['final_cash'], reverse=True)
    for i, result in enumerate(sorted_by_cash, 1):
        print(f"  {i}. {result['sma_combo']:<12} 現有現金 ${result['final_cash']:>10,.0f}")

    # 詳細分析
    print("\n" + "="*150)
    print("🔍 詳細分析")
    print("="*150)

    for result in results:
        print(f"\n【{result['sma_combo']}】")
        print(f"  進場次數：{result['num_trades']} 次")
        print(f"  出場次數：{result['num_exits']} 次")
        print(f"  已實現：${result['total_realized_pnl']:+,.0f} ({result['realized_return_pct']:+.2f}%)")
        print(f"  現有現金：${result['final_cash']:,.0f}")
        print(f"  持倉金額：${result['final_position_value']:,.0f}")
        print(f"  總資產：${result['final_total_value']:,.0f} ({result['total_return_pct']:+.2f}%)")

