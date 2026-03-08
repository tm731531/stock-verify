"""
V7 策略 6週 vs 90天 對比回測
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

print("="*80)
print("V7 策略回測：6週 vs 90天 對比")
print("="*80)

# ── 加載基本數據 ──

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
        if (float(rows[i]['ratio_400_above'] or 0) > float(rows[i-1]['ratio_400_above'] or 0) and
            float(rows[i-1]['ratio_400_above'] or 0) > float(rows[i-2]['ratio_400_above'] or 0) and
            float(rows[i-2]['ratio_400_above'] or 0) > float(rows[i-3]['ratio_400_above'] or 0)):

            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)
            if r400_chg >= 3.0:
                r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-3]['ratio_1000_above'] or 0)
                sync_ratio = r1000_chg / max(r400_chg, 0.001)
                holder_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                             max(float(rows[i-3]['total_holders'] or 1), 1) * 100)

                if sync_ratio >= 0.5 and holder_chg <= -2.0:
                    signals.append({'stock': stock_code, 'signal_date': rows[i]['date'], 'engine': 'main'})

        holder_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                     max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
        r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

        if holder_chg <= -15.0 and r400_chg >= 2.0:
            signals.append({'stock': stock_code, 'signal_date': rows[i]['date'], 'engine': 'backup'})

conn.close()

print(f"✓ 交易日: {len(all_dates)} 個")
print(f"✓ 股票: {len(all_stocks)} 支")
print(f"✓ 識別信號：{len(signals)} 個")

# ── 回測參數 ──
CAPITAL = 500_000
MAX_POSITIONS = 6
PER_POSITION = CAPITAL // MAX_POSITIONS
STOP_LOSS_PCT = -7.0
TRAILING_ACTIVATE_PCT = 15.0
TRAILING_STOP_PCT = 10.0
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
TOTAL_SELL_COST = SELL_FEE + SELL_TAX

# ── 回測函數 ──

def backtest(hold_days, hold_label):
    print(f"\n{'='*80}")
    print(f"回測：持倉期 {hold_label} ({hold_days} 天)")
    print(f"{'='*80}\n")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    trades = []
    positions = {}
    cash = CAPITAL
    pending_orders = {}

    # 準備進場
    for sig in signals:
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
            days_held = (datetime.strptime(current_date, '%Y%m%d') - datetime.strptime(pos['buy_date'], '%Y%m%d')).days
            gross_ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            net_ret = gross_ret - TOTAL_SELL_COST * 100

            should_exit = False
            exit_reason = 'hold'

            if gross_ret <= STOP_LOSS_PCT:
                should_exit = True
                exit_reason = 'stop_loss'
                net_ret = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
            elif gross_ret >= TRAILING_ACTIVATE_PCT and not pos.get('trailing'):
                pos['trailing'] = True
                pos['trailing_high'] = current_price

            if pos.get('trailing'):
                pullback = (current_price - pos['trailing_high']) / pos['trailing_high'] * 100
                if pullback <= -TRAILING_STOP_PCT:
                    should_exit = True
                    exit_reason = 'trailing'
                else:
                    pos['trailing_high'] = max(pos['trailing_high'], current_price)

            if not should_exit and days_held >= hold_days:
                should_exit = True
                exit_reason = 'hold_period'

            if should_exit:
                pnl = pos['invested'] * net_ret / 100
                cash += pos['invested'] + pnl
                trades.append({
                    'engine': pos['engine'], 'stock': stock_code,
                    'buy_date': pos['buy_date'], 'exit_date': current_date,
                    'entry_price': pos['entry_price'], 'exit_price': current_price,
                    'days_held': days_held, 'gross_return_pct': gross_ret,
                    'net_return_pct': net_ret, 'pnl_twd': round(pnl),
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

            if current_idx < entry_start_idx:
                continue

            if len(positions) >= MAX_POSITIONS or stock_code in positions or cash < PER_POSITION:
                continue

            cursor.execute("SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
                (stock_code, current_date))
            price_row = cursor.fetchone()
            if not price_row or not price_row['close_price']:
                continue

            current_price = float(price_row['close_price'])
            limit_price = min(order['signal_price'], current_price)

            if limit_price < 50.0:
                continue

            shares = int(PER_POSITION / (limit_price * (1 + BUY_FEE)))
            if shares <= 0:
                continue

            invested = shares * limit_price * (1 + BUY_FEE)
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
        net_ret = gross_ret - TOTAL_SELL_COST * 100
        pnl = pos['invested'] * net_ret / 100
        cash += pos['invested'] + pnl
        trades.append({
            'engine': pos['engine'], 'stock': stock_code,
            'buy_date': pos['buy_date'], 'exit_date': last_date,
            'entry_price': pos['entry_price'], 'exit_price': exit_price,
            'days_held': 'open', 'gross_return_pct': gross_ret,
            'net_return_pct': net_ret, 'pnl_twd': round(pnl),
            'exit_reason': 'data_end',
        })

    conn.close()

    # 統計
    if trades:
        trades_df = pd.DataFrame(trades)
        total_pnl = trades_df['pnl_twd'].sum()
        final_equity = CAPITAL + total_pnl
        wins = (trades_df['net_return_pct'] > 0).sum()
        win_rate = wins / len(trades_df) * 100
        year_count = 3.27

        print(f"初始資本: {CAPITAL:,} 元")
        print(f"最終淨值: {final_equity:,.0f} 元")
        print(f"總利潤: {total_pnl:+,} 元")
        print(f"總報酬率: {total_pnl/CAPITAL*100:+.2f}%")
        print(f"年化報酬: {(total_pnl/CAPITAL*100)/year_count:.1f}%")
        print(f"\n交易統計:")
        print(f"  總筆數: {len(trades_df)}")
        print(f"  勝率: {win_rate:.1f}%")
        print(f"  平均回報: {trades_df['net_return_pct'].mean():+.2f}%")

        print(f"\n引擎表現:")
        for engine in ['main', 'backup']:
            e_trades = trades_df[trades_df['engine'] == engine]
            if len(e_trades) > 0:
                e_wins = (e_trades['net_return_pct'] > 0).sum()
                e_pnl = e_trades['pnl_twd'].sum()
                print(f"  {engine.upper()}: {len(e_trades)} 筆, 勝率 {e_wins/len(e_trades)*100:.1f}%, 利潤 {e_pnl:+,} 元")

        return {
            'hold_days': hold_days, 'hold_label': hold_label, 'total_pnl': total_pnl,
            'final_equity': final_equity, 'return_pct': total_pnl/CAPITAL*100,
            'annual_return': (total_pnl/CAPITAL*100)/year_count, 'trades': len(trades_df),
            'win_rate': win_rate, 'avg_return': trades_df['net_return_pct'].mean(),
        }

# ── 執行回測 ──

result_6week = backtest(42, "6週")
result_90day = backtest(90, "90天")

# ── 對比 ──

print(f"\n{'='*80}")
print("對比結果：6週 vs 90天")
print(f"{'='*80}\n")

print(f"{'指標':<15} {'6週':>15} {'90天':>15} {'差異':>15}")
print(f"{'-'*60}")
print(f"{'年化報酬':<15} {result_6week['annual_return']:>14.1f}% {result_90day['annual_return']:>14.1f}% {result_6week['annual_return']-result_90day['annual_return']:>+14.1f}%")
print(f"{'總利潤':<15} {result_6week['total_pnl']:>14,} {result_90day['total_pnl']:>14,} {result_6week['total_pnl']-result_90day['total_pnl']:>+14,}")
print(f"{'交易筆數':<15} {result_6week['trades']:>15} {result_90day['trades']:>15} {result_6week['trades']-result_90day['trades']:>+15}")
print(f"{'勝率':<15} {result_6week['win_rate']:>14.1f}% {result_90day['win_rate']:>14.1f}% {result_6week['win_rate']-result_90day['win_rate']:>+14.1f}%")
print(f"{'平均回報':<15} {result_6week['avg_return']:>14.2f}% {result_90day['avg_return']:>14.2f}% {result_6week['avg_return']-result_90day['avg_return']:>+14.2f}%")

if result_6week['annual_return'] > result_90day['annual_return']:
    diff = result_6week['annual_return'] - result_90day['annual_return']
    print(f"\n✅ 6週優於90天，年化多出 {diff:.1f}%")
else:
    diff = result_90day['annual_return'] - result_6week['annual_return']
    print(f"\n❌ 90天優於6週，年化多出 {diff:.1f}%")

print(f"\n{'='*80}")
