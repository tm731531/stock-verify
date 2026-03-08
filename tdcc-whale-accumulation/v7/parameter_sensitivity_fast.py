"""
v7 策略快速參數敏感性分析
只測試最關鍵的5個參數，用於快速生成報告
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pandas as pd
import numpy as np

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

# 只測試5個關鍵參數
FAST_PARAMETERS = {
    'stop_loss_pct': [-5.0, -7.0, -10.0],
    'max_hold_days': [30, 42, 60, 90],
    'min_price_main': [200, 300, 500],
    'trailing_activate_pct': [10.0, 15.0, 20.0],
    'min_sync': [0.3, 0.5, 0.7, 0.9],
}

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
print("v7 策略快速參數敏感性分析（5個關鍵參數）")
print("="*80)

# 加載數據
print("\n加載數據...")
conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

cursor.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_index = {d: i for i, d in enumerate(all_dates)}

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

# 簡化訊號識別（只做主引擎）
signals = []
for stock_code in all_stocks[:500]:  # 只用前500支股票加快速度
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings WHERE stock_code = %s ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 4:
        continue

    for i in range(3, len(rows)):
        r400_streak = 0
        for j in range(i, 0, -1):
            if float(rows[j]['ratio_400_above'] or 0) > float(rows[j-1]['ratio_400_above'] or 0):
                r400_streak += 1
            else:
                break

        if r400_streak >= 3:
            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-r400_streak]['ratio_400_above'] or 0)
            if r400_chg >= 3.0:
                r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-r400_streak]['ratio_1000_above'] or 0)
                sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
                holders_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-r400_streak]['total_holders'] or 0)) /
                              max(float(rows[i-r400_streak]['total_holders'] or 1), 1) * 100)

                if sync >= 0.5 and holders_chg <= -2.0:
                    signals.append({
                        'stock': stock_code, 'signal_date': rows[i]['date'], 'engine': 'main',
                        'r400_chg': r400_chg, 'sync': sync, 'streak': r400_streak
                    })

conn.close()

print(f"✓ 識別訊號：{len(signals)} 個")

# 簡化回測函數
def quick_backtest(config, signals, all_dates, date_index):
    """快速回測（簡化版）"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    capital = config['capital']
    per_position = capital // config['max_positions']
    total_sell_cost = config['sell_fee'] + config['sell_tax']

    # 篩選訊號
    filtered_signals = []
    for sig in signals:
        if (sig['r400_chg'] >= config['min_r400_chg'] and
            sig['sync'] >= config['min_sync'] and
            sig['streak'] >= config['min_streak']):
            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (sig['stock'], sig['signal_date']))
            price_row = cursor.fetchone()
            if price_row and float(price_row['close_price'] or 0) >= config['min_price_main']:
                filtered_signals.append(sig)

    # 準備進場
    pending_orders = {}
    for sig in filtered_signals:
        cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
            (sig['stock'], sig['signal_date']))
        price_row = cursor.fetchone()
        if not price_row:
            continue
        signal_price = float(price_row['close_price'])
        if sig['stock'] not in pending_orders:
            pending_orders[sig['stock']] = {
                'signal_date': sig['signal_date'],
                'signal_price': signal_price,
                'signal_date_idx': date_index.get(sig['signal_date'], 0),
            }

    # 遍歷交易日
    trades = []
    positions = {}
    cash = capital

    for current_idx, current_date in enumerate(all_dates):
        # 簡化的出場邏輯
        exited = []
        for stock_code, pos in list(positions.items()):
            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (stock_code, current_date))
            price_row = cursor.fetchone()
            if not price_row:
                continue

            current_price = float(price_row['close_price'])
            buy_date_obj = datetime.strptime(pos['buy_date'], '%Y%m%d')
            current_date_obj = datetime.strptime(current_date, '%Y%m%d')
            days = (current_date_obj - buy_date_obj).days

            ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100

            should_exit = False
            if ret <= config['stop_loss_pct']:
                should_exit = True
            elif days >= config['max_hold_days']:
                should_exit = True

            if should_exit:
                net = ret - total_sell_cost * 100
                pnl = pos['invested'] * net / 100
                cash += pos['invested'] + pnl
                trades.append({'pnl_twd': round(pnl), 'return_pct': net})
                exited.append(stock_code)

        for stock_code in exited:
            del positions[stock_code]

        # 簡化的進場邏輯
        for stock_code, order in list(pending_orders.items()):
            if len(positions) >= config['max_positions'] or stock_code in positions:
                continue

            signal_idx = order['signal_date_idx']
            entry_start = min(signal_idx + 3, len(all_dates) - 1)
            entry_end = min(signal_idx + 8, len(all_dates) - 1)

            if current_idx < entry_start or current_idx > entry_end:
                continue

            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (stock_code, current_date))
            price_row = cursor.fetchone()
            if not price_row or cash < per_position:
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
                'buy_date': current_date, 'entry_price': limit_price,
                'shares': shares, 'invested': invested
            }
            del pending_orders[stock_code]

    conn.close()

    if not trades:
        return {'return_pct': 0, 'total_pnl': 0, 'trades': 0}

    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df['pnl_twd'].sum()
    return {
        'return_pct': total_pnl / capital * 100,
        'total_pnl': total_pnl,
        'trades': len(trades_df),
    }

# 執行掃描
print("\n執行快速參數掃描...\n")
results = {}

for param_name, param_values in FAST_PARAMETERS.items():
    print(f"{param_name}:")
    param_results = []

    for test_value in param_values:
        test_config = BASE_CONFIG.copy()
        test_config[param_name] = test_value

        result = quick_backtest(test_config, signals, all_dates, date_index)
        param_results.append({
            'value': test_value,
            'return_pct': result['return_pct'],
            'total_pnl': result['total_pnl'],
            'trades': result['trades'],
        })

        print(f"  {param_name}={test_value:>6} → 報酬 {result['return_pct']:>+6.1f}%  利潤 {result['total_pnl']:>+10,}  {result['trades']}筆")

    results[param_name] = param_results

# 輸出總結
print("\n" + "="*80)
print("快速分析結果總結")
print("="*80)

results_summary = []
for param_name, param_results in results.items():
    best = max(param_results, key=lambda x: x['return_pct'])
    baseline = [r for r in param_results if r['value'] == BASE_CONFIG[param_name]][0]
    improvement = best['return_pct'] - baseline['return_pct']

    results_summary.append({
        'Parameter': param_name,
        'Best Value': best['value'],
        'Best Return': best['return_pct'],
        'Current Value': BASE_CONFIG[param_name],
        'Current Return': baseline['return_pct'],
        'Improvement': improvement,
    })
    print(f"\n{param_name}:")
    print(f"  當前值: {BASE_CONFIG[param_name]} (報酬 {baseline['return_pct']:+.1f}%)")
    print(f"  最優值: {best['value']} (報酬 {best['return_pct']:+.1f}%)")
    print(f"  提升: {improvement:+.1f}pp")

results_df = pd.DataFrame(results_summary).sort_values('Improvement', ascending=False)
results_df.to_csv('/tmp/parameter_sensitivity_fast_results.csv', index=False)

print("\n✓ 快速分析完成，結果已保存到 /tmp/parameter_sensitivity_fast_results.csv")
