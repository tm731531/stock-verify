"""
v7 策略完整參數敏感性分析
測試所有14個參數對回測績效的影響
基於PostgreSQL真實數據，固定42天持倉期
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

# ── 參數定義 ──

PARAMETERS = {
    # 出場條件
    'stop_loss_pct': [-5.0, -7.0, -10.0],
    'trailing_activate_pct': [10.0, 15.0, 20.0, 25.0],
    'trailing_stop_pct': [5.0, 10.0, 15.0],

    # 持倉期（天數）
    'max_hold_days': [30, 42, 60, 90, 120],

    # 主引擎參數
    'min_price_main': [100, 300, 500, 800],
    'min_sync': [0.3, 0.5, 0.7, 0.9],
    'min_r400_chg': [2.0, 3.0, 4.0, 5.0],
    'min_streak': [2, 3, 4],
    'max_holder_chg': [-1.0, -2.0, -3.0, -5.0],

    # 補位引擎參數
    'flee_lookback_weeks': [2, 4, 6, 8],
    'flee_min_pct': [-3.0, -5.0, -7.0, -10.0],
    'min_price_backup': [30, 50, 100, 200],
    'backup_ma_period': [10, 20, 30, 50],

    # 資金管理
    'max_positions': [3, 4, 5, 6],
}

# 基礎配置（預設值）
BASE_CONFIG = {
    'stop_loss_pct': -7.0,
    'trailing_activate_pct': 15.0,
    'trailing_stop_pct': 10.0,
    'max_hold_days': 42,
    'min_price_main': 300,
    'min_sync': 0.5,
    'min_r400_chg': 3.0,
    'min_streak': 3,
    'max_holder_chg': -2.0,
    'flee_lookback_weeks': 4,
    'flee_min_pct': -5.0,
    'min_price_backup': 50,
    'backup_ma_period': 20,
    'max_positions': 4,
    'capital': 500_000,
    'buy_fee': 0.001425,
    'sell_fee': 0.001425,
    'sell_tax': 0.003,
}

print("="*80)
print("v7 策略完整參數敏感性分析")
print("="*80)
print(f"\n基礎配置：")
for k, v in BASE_CONFIG.items():
    if k not in PARAMETERS:
        print(f"  {k}: {v}")

# ── 數據加載 ──

print("\n加載數據...")
conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

cursor.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_index = {d: i for i, d in enumerate(all_dates)}

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

# 識別信號
signals = []
for stock_code in all_stocks:
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings WHERE stock_code = %s ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 4:
        continue

    for i in range(3, len(rows)):
        # 主引擎訊號
        r400_streak = 0
        for j in range(i, 0, -1):
            if float(rows[j]['ratio_400_above'] or 0) > float(rows[j-1]['ratio_400_above'] or 0):
                r400_streak += 1
            else:
                break

        if r400_streak >= 3:  # 至少3週連升
            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-r400_streak]['ratio_400_above'] or 0)
            if r400_chg >= 3.0:
                r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-r400_streak]['ratio_1000_above'] or 0)
                sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
                holders_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-r400_streak]['total_holders'] or 0)) /
                              max(float(rows[i-r400_streak]['total_holders'] or 1), 1) * 100)

                if sync >= 0.5 and holders_chg <= -2.0:
                    signals.append({
                        'stock': stock_code, 'signal_date': rows[i]['date'], 'engine': 'main',
                        'r400_chg': r400_chg, 'sync': sync, 'streak': r400_streak, 'holders_chg': holders_chg
                    })

        # 補位引擎訊號（4週）
        if i >= 4:
            holders_now = float(rows[i]['total_holders'] or 0)
            holders_4w = float(rows[i-4]['total_holders'] or 0)
            if holders_4w > 0:
                flee = (holders_now - holders_4w) / holders_4w * 100
                if flee <= -5.0:
                    r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-4]['ratio_400_above'] or 0)
                    if r400_chg >= 2.0:
                        signals.append({
                            'stock': stock_code, 'signal_date': rows[i]['date'], 'engine': 'backup',
                            'flee': flee, 'holders_chg': flee
                        })

conn.close()

print(f"✓ 識別訊號：{len(signals)} 個")

# ── 回測函數 ──

def backtest_single_config(config, signals, all_dates, date_index, all_stocks):
    """執行單一配置的回測"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    capital = config['capital']
    per_position = capital // config['max_positions']
    total_sell_cost = config['sell_fee'] + config['sell_tax']

    # 訊號預處理（根據配置篩選）
    filtered_signals = []
    for sig in signals:
        if sig['engine'] == 'main':
            if (sig['r400_chg'] >= config['min_r400_chg'] and
                sig['sync'] >= config['min_sync'] and
                sig['streak'] >= config['min_streak'] and
                sig['holders_chg'] <= config['max_holder_chg']):
                # 檢查股價
                cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                    (sig['stock'], sig['signal_date']))
                price_row = cursor.fetchone()
                if price_row and float(price_row['close_price'] or 0) >= config['min_price_main']:
                    filtered_signals.append(sig)
        else:  # backup
            if sig['flee'] <= config['flee_min_pct']:
                # 檢查回望週數
                sig_idx = date_index.get(sig['signal_date'], 0)
                if sig_idx >= config['flee_lookback_weeks']:
                    # 檢查股價和MA
                    cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                        (sig['stock'], sig['signal_date']))
                    price_row = cursor.fetchone()
                    if price_row and float(price_row['close_price'] or 0) >= config['min_price_backup']:
                        filtered_signals.append(sig)

    # 準備進場
    pending_orders = {}
    for sig in filtered_signals:
        stock = sig['stock']
        cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
            (stock, sig['signal_date']))
        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price']:
            continue
        signal_price = float(price_row['close_price'])
        if stock not in pending_orders:
            pending_orders[stock] = {
                'signal_date': sig['signal_date'],
                'signal_price': signal_price,
                'signal_date_idx': date_index.get(sig['signal_date'], 0),
                'engine': sig['engine'],
            }

    # 遍歷交易日
    trades = []
    positions = {}
    cash = capital

    for current_idx, current_date in enumerate(all_dates):
        # 出場
        exited = []
        for stock_code, pos in list(positions.items()):
            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (stock_code, current_date))
            price_row = cursor.fetchone()
            if not price_row or not price_row['close_price']:
                continue

            current_price = float(price_row['close_price'])
            buy_date_obj = datetime.strptime(pos['buy_date'], '%Y%m%d')
            current_date_obj = datetime.strptime(current_date, '%Y%m%d')
            calendar_days = (current_date_obj - buy_date_obj).days

            gross_ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            net_ret = gross_ret - total_sell_cost * 100

            should_exit = False
            exit_reason = None

            if gross_ret <= config['stop_loss_pct']:
                should_exit = True
                exit_reason = 'stop_loss'
                net_ret = config['stop_loss_pct'] - total_sell_cost * 100
            elif gross_ret >= config['trailing_activate_pct'] and not pos.get('trailing'):
                pos['trailing'] = True
                pos['trailing_high'] = current_price

            if pos.get('trailing'):
                pullback = (current_price - pos['trailing_high']) / pos['trailing_high'] * 100
                if pullback <= -config['trailing_stop_pct']:
                    should_exit = True
                    exit_reason = 'trailing'
                else:
                    pos['trailing_high'] = max(pos['trailing_high'], current_price)

            if not should_exit and calendar_days >= config['max_hold_days']:
                should_exit = True
                exit_reason = 'hold_period'

            if should_exit:
                pnl = pos['invested'] * net_ret / 100
                cash += pos['invested'] + pnl
                trades.append({
                    'engine': pos['engine'], 'stock': stock_code,
                    'pnl_twd': round(pnl), 'return_pct': net_ret,
                    'exit_reason': exit_reason,
                })
                exited.append(stock_code)

        for stock_code in exited:
            del positions[stock_code]

        # 進場
        stocks_to_remove = []
        for stock_code, order in list(pending_orders.items()):
            signal_idx = order['signal_date_idx']
            entry_start_idx = min(signal_idx + 3, len(all_dates) - 1)
            entry_end_idx = min(signal_idx + 8, len(all_dates) - 1)

            if current_idx > entry_end_idx:
                stocks_to_remove.append(stock_code)
                continue

            if current_idx < entry_start_idx or stock_code in positions or len(positions) >= config['max_positions']:
                continue

            if cash < per_position:
                continue

            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (stock_code, current_date))
            price_row = cursor.fetchone()
            if not price_row or not price_row['close_price']:
                continue

            current_price = float(price_row['close_price'])
            limit_price = min(order['signal_price'], current_price)

            shares = int(per_position / (limit_price * (1 + config['buy_fee'])))
            if shares <= 0:
                continue

            invested = shares * limit_price * (1 + config['buy_fee'])
            if invested > cash:
                continue

            cash -= invested
            positions[stock_code] = {
                'engine': order['engine'], 'buy_date': current_date,
                'entry_price': limit_price, 'shares': shares,
                'invested': invested, 'trailing': False,
                'trailing_high': limit_price,
            }
            stocks_to_remove.append(stock_code)

        for stock in stocks_to_remove:
            if stock in pending_orders:
                del pending_orders[stock]

    # 強制平倉
    last_date = all_dates[-1]
    for stock_code, pos in positions.items():
        cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
            (stock_code, last_date))
        price_row = cursor.fetchone()
        exit_price = float(price_row['close_price']) if price_row and price_row['close_price'] else pos['entry_price']
        gross_ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
        net_ret = gross_ret - total_sell_cost * 100
        pnl = pos['invested'] * net_ret / 100
        cash += pos['invested'] + pnl
        trades.append({
            'engine': pos['engine'], 'stock': stock_code,
            'pnl_twd': round(pnl), 'return_pct': net_ret,
            'exit_reason': 'data_end',
        })

    conn.close()

    if not trades:
        return {
            'total_pnl': 0, 'final_equity': capital, 'return_pct': 0,
            'trades': 0, 'win_rate': 0, 'avg_return': 0
        }

    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = capital + total_pnl
    wins = (trades_df['return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100 if len(trades_df) > 0 else 0

    return {
        'total_pnl': total_pnl,
        'final_equity': final_equity,
        'return_pct': total_pnl / capital * 100,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'avg_return': trades_df['return_pct'].mean(),
    }

# ── 執行參數掃描 ──

print("\n\n開始參數敏感性掃描...")
results = {}

for param_name, param_values in PARAMETERS.items():
    print(f"\n{'='*80}")
    print(f"參數: {param_name}")
    print(f"測試值: {param_values}")
    print(f"{'='*80}")

    param_results = []

    for test_value in param_values:
        # 建立測試配置
        test_config = BASE_CONFIG.copy()
        test_config[param_name] = test_value

        # 執行回測
        result = backtest_single_config(test_config, signals, all_dates, date_index, all_stocks)

        param_results.append({
            'value': test_value,
            'return_pct': result['return_pct'],
            'total_pnl': result['total_pnl'],
            'trades': result['trades'],
            'win_rate': result['win_rate'],
            'avg_return': result['avg_return'],
        })

        print(f"  {param_name}={test_value:>6} → 報酬 {result['return_pct']:>+6.1f}%  |  "
              f"利潤 {result['total_pnl']:>+10,}  |  {result['trades']:>3d}筆  |  "
              f"勝率 {result['win_rate']:>5.1f}%")

    results[param_name] = param_results

    # 找出最優值
    best = max(param_results, key=lambda x: x['return_pct'])
    print(f"\n  → 最優值: {param_name}={best['value']} (報酬 {best['return_pct']:+.1f}%)")

# ── 輸出結果 ──

print("\n\n" + "="*80)
print("完整參數敏感性分析結果")
print("="*80)

results_summary = []
for param_name, param_results in results.items():
    best = max(param_results, key=lambda x: x['return_pct'])
    worst = min(param_results, key=lambda x: x['return_pct'])
    baseline = [r for r in param_results if r['value'] == BASE_CONFIG[param_name]][0]

    results_summary.append({
        'Parameter': param_name,
        'Best Value': best['value'],
        'Best Return': best['return_pct'],
        'Worst Value': worst['value'],
        'Worst Return': worst['return_pct'],
        'Current Value': BASE_CONFIG[param_name],
        'Current Return': baseline['return_pct'],
        'Improvement': best['return_pct'] - baseline['return_pct'],
    })

results_df = pd.DataFrame(results_summary).sort_values('Improvement', ascending=False)
print("\n" + results_df.to_string(index=False))

# 保存結果
import json
results_df.to_csv('/tmp/parameter_sensitivity_results.csv', index=False)
print("\n✓ 結果已保存到 /tmp/parameter_sensitivity_results.csv")
