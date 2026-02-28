#!/usr/bin/env python3
"""
$100k 單筆交易 SMA 系統回測
=============================
基於實際現金流的績效分析

配置:
- 單筆交易額: $100,000
- 倉位上限: $300,000 (最多 3 筆)
- 現金保留: 始終保有 $200,000+
- 出場邏輯: 分批獲利 (5%, 10%) + 快速止損
"""

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path


def backtest_100k_strategy(csv_path: str) -> dict:
    """運行 $100k 單筆配置的回測"""

    # 載入數據
    df = pd.read_csv(csv_path, index_col='Date', parse_dates=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

    # 計算指標
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()

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

    trades = []  # 記錄所有交易
    monthly_realized = {}  # 每月已實現現金
    daily_cash_flow = []  # 每日現金流狀態

    # 回測迴圈
    for idx, row in df.iterrows():
        date = idx
        close = row['Close']
        sma50 = row['SMA_50']
        sma200 = row['SMA_200']
        atr = row['ATR']
        atr_ma = row['ATR_MA']
        daily_ret = row['Daily_Return']

        # 檢查資料完整性
        if pd.isna(sma50) or pd.isna(sma200):
            continue

        month_key = date.strftime('%Y-%m')

        # ===== 出場檢查 =====
        if shares_held > 0:
            current_value = shares_held * close
            unrealized_pnl = current_value - position_value
            unrealized_pnl_pct = (unrealized_pnl / position_value) * 100 if position_value > 0 else 0

            # 規則 1: 快速止損 (警訊 + 大跌)
            if pd.notna(atr) and pd.notna(atr_ma) and atr_ma > 0:
                if atr > atr_ma * 1.5 and daily_ret < -0.03:
                    # 快速全出
                    realized_pnl = current_value - position_value
                    cash += current_value
                    trades.append({
                        'date': date,
                        'type': 'exit_stop_loss',
                        'entry_date': entry_date,
                        'entry_price': entry_price,
                        'exit_price': close,
                        'shares': shares_held,
                        'position_value': position_value,
                        'exit_value': current_value,
                        'realized_pnl': realized_pnl,
                        'realized_pnl_pct': (realized_pnl / position_value) * 100
                    })

                    if month_key not in monthly_realized:
                        monthly_realized[month_key] = 0
                    monthly_realized[month_key] += realized_pnl

                    shares_held = 0
                    position_value = 0
                    entry_price = 0
                    entry_date = None

            # 規則 2: 死亡交叉快速全出
            elif sma50 < sma200 and shares_held > 0:
                realized_pnl = current_value - position_value
                cash += current_value
                trades.append({
                    'date': date,
                    'type': 'exit_death_cross',
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'shares': shares_held,
                    'position_value': position_value,
                    'exit_value': current_value,
                    'realized_pnl': realized_pnl,
                    'realized_pnl_pct': (realized_pnl / position_value) * 100
                })

                if month_key not in monthly_realized:
                    monthly_realized[month_key] = 0
                monthly_realized[month_key] += realized_pnl

                shares_held = 0
                position_value = 0
                entry_price = 0
                entry_date = None

            # 規則 3: 分批獲利出場 (+5%, +10%)
            elif unrealized_pnl_pct >= 10 and shares_held > 0:
                # 賣出 25% (取出第二層獲利)
                sell_shares = shares_held * 0.25
                sell_value = sell_shares * close
                realized_pnl = sell_value - (position_value * 0.25)
                cash += sell_value
                shares_held -= sell_shares
                position_value -= (position_value * 0.25)

                trades.append({
                    'date': date,
                    'type': 'partial_exit_10pct',
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'shares': sell_shares,
                    'position_value': sell_value,
                    'exit_value': sell_value,
                    'realized_pnl': realized_pnl,
                    'realized_pnl_pct': (realized_pnl / (position_value + realized_pnl)) * 100
                })

                if month_key not in monthly_realized:
                    monthly_realized[month_key] = 0
                monthly_realized[month_key] += realized_pnl

            elif unrealized_pnl_pct >= 5 and shares_held > 0:
                # 賣出 50% (取出第一層獲利)
                sell_shares = shares_held * 0.5
                sell_value = sell_shares * close
                realized_pnl = sell_value - (position_value * 0.5)
                cash += sell_value
                shares_held -= sell_shares
                position_value -= (position_value * 0.5)

                trades.append({
                    'date': date,
                    'type': 'partial_exit_5pct',
                    'entry_date': entry_date,
                    'entry_price': entry_price,
                    'exit_price': close,
                    'shares': sell_shares,
                    'position_value': sell_value,
                    'exit_value': sell_value,
                    'realized_pnl': realized_pnl,
                    'realized_pnl_pct': (realized_pnl / (position_value + realized_pnl)) * 100
                })

                if month_key not in monthly_realized:
                    monthly_realized[month_key] = 0
                monthly_realized[month_key] += realized_pnl

        # ===== 進場檢查 =====
        # 只有在無倉位且有現金時才進場
        if shares_held == 0 and cash >= single_trade_amount + min_cash_buffer:
            # 黃金交叉進場訊號
            if sma50 > sma200:
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
                            'entry_price': entry_price,
                            'entry_date': entry_date,
                            'shares': shares_bought,
                            'position_value': position_value,
                            'cash_remaining': cash
                        })

        # 或加倉（如果看漲且有額外現金）
        elif shares_held > 0 and sma50 > sma200 and position_value < max_position:
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
                        'add_price': close,
                        'add_shares': add_shares,
                        'total_position_value': position_value,
                        'cash_remaining': cash
                    })

        # 記錄每日狀態
        daily_cash_flow.append({
            'date': date,
            'price': close,
            'cash': cash,
            'position_value': position_value,
            'total_value': cash + position_value,
            'shares': shares_held,
            'sma50': sma50,
            'sma200': sma200
        })

    # 計算統計
    final_value = cash + (shares_held * df['Close'].iloc[-1])
    total_realized = sum(monthly_realized.values())
    total_invested = initial_capital - initial_capital

    return {
        'trades': trades,
        'monthly_realized': monthly_realized,
        'daily_cash_flow': daily_cash_flow,
        'initial_capital': initial_capital,
        'final_cash': cash,
        'final_position_value': position_value,
        'final_total_value': final_value,
        'total_realized_pnl': total_realized,
        'unrealized_pnl': final_value - initial_capital - total_realized,
        'total_return_pct': ((final_value - initial_capital) / initial_capital) * 100,
        'realized_return_pct': (total_realized / initial_capital) * 100
    }


def print_report(results: dict):
    """印出詳細報告"""

    print("\n" + "=" * 100)
    print("$100,000 單筆交易 SMA 系統 - 回測報告")
    print("=" * 100)

    print(f"\n初始資本: ${results['initial_capital']:,.0f}")
    print(f"回測期間: 2020-01-01 → 2026-02-26")

    print(f"\n{'-' * 100}")
    print("📊 績效總結")
    print(f"{'-' * 100}")

    print(f"\n最終資產配置:")
    print(f"  現金: ${results['final_cash']:,.0f}")
    print(f"  倉位價值: ${results['final_position_value']:,.0f}")
    print(f"  總資產: ${results['final_total_value']:,.0f}")

    print(f"\n✅ 已實現收益: ${results['total_realized_pnl']:+,.0f} ({results['realized_return_pct']:+.2f}%)")
    print(f"📈 未實現收益: ${results['unrealized_pnl']:+,.0f}")
    print(f"💰 總收益: ${results['final_total_value'] - results['initial_capital']:+,.0f} ({results['total_return_pct']:+.2f}%)")

    print(f"\n{'-' * 100}")
    print("📅 月度已實現現金")
    print(f"{'-' * 100}\n")

    sorted_months = sorted(results['monthly_realized'].items())
    for month, realized in sorted_months:
        if realized != 0:
            print(f"{month}: ${realized:+,.0f}")

    print(f"\n{'-' * 100}")
    print("交易統計")
    print(f"{'-' * 100}")

    trades = results['trades']
    entries = [t for t in trades if t['type'] == 'entry']
    exits = [t for t in trades if 'exit' in t['type']]
    partial = [t for t in trades if 'partial' in t['type']]
    adds = [t for t in trades if t['type'] == 'add_position']

    print(f"\n進場次數: {len(entries)}")
    print(f"加倒次數: {len(adds)}")
    print(f"部分出場: {len(partial)}")
    print(f"完全出場: {len([t for t in exits if 'exit' in t['type']])}")

    if exits:
        exit_pnls = [t.get('realized_pnl', 0) for t in exits if 'realized_pnl' in t]
        if exit_pnls:
            print(f"\n出場交易:")
            print(f"  平均獲利: ${np.mean(exit_pnls):+,.0f}")
            print(f"  最大獲利: ${np.max(exit_pnls):+,.0f}")
            print(f"  最大虧損: ${np.min(exit_pnls):+,.0f}")
            winning = len([p for p in exit_pnls if p > 0])
            print(f"  勝率: {winning}/{len(exit_pnls)} ({winning/len(exit_pnls)*100:.0f}%)")

    print(f"\n{'-' * 100}\n")


# 執行回測
if __name__ == '__main__':
    csv_path = '006208-sma-market-regime/data/006208_historical.csv'

    results = backtest_100k_strategy(csv_path)
    print_report(results)

    # 儲存詳細結果為 JSON
    import json
    with open('backtest_100k_results.json', 'w', encoding='utf-8') as f:
        # 轉換為可序列化格式
        results_serializable = results.copy()
        results_serializable['trades'] = [
            {k: v.isoformat() if isinstance(v, pd.Timestamp) else v
             for k, v in t.items()}
            for t in results['trades']
        ]
        results_serializable['monthly_realized'] = {
            k: float(v) for k, v in results['monthly_realized'].items()
        }
        json.dump(results_serializable, f, indent=2, ensure_ascii=False, default=str)

    print("✅ 詳細結果已保存到 backtest_100k_results.json")
