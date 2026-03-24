#!/usr/bin/env python3
"""
6週版本回測 - 實盤進場邏輯（簡化版）

邏輯：
  1. 識別 TDCC 信號
  2. 信號日期後 3 日開始、5 個交易日內嘗試進場
  3. 進場價 = MIN(信號日收盤, 進場日收盤)
  4. 超過 5 日就放棄
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="tdcc",
        user="tdcc",
        password="tdcc1234"
    )

print("="*80)
print("回測：6週版本（實盤進場邏輯 v2 - 簡化）")
print("="*80)

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 加載所有交易日期
cursor.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_index = {d: i for i, d in enumerate(all_dates)}

print(f"✓ 加載 {len(all_dates)} 個交易日")

# 加載所有股票
cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]
print(f"✓ 加載 {len(all_stocks)} 支股票")

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
        # 主引擎：3週連升 ≥3%，同步比 ≥50%，散戶逃離 ≥2%
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
                    signals.append({
                        'stock': stock_code,
                        'signal_date': rows[i]['date'],
                        'engine': 'main',
                        'min_price': 300.0,
                    })

        # 備用引擎：3週散戶逃離 ≥15%，大戶增加 ≥2%
        holder_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                     max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
        r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

        if holder_chg <= -15.0 and r400_chg >= 2.0:
            signals.append({
                'stock': stock_code,
                'signal_date': rows[i]['date'],
                'engine': 'backup',
                'min_price': 50.0,
            })

print(f"✓ 識別信號：{len(signals)} 個")

# 回測參數
CAPITAL = 500_000
MAX_POSITIONS = 6
PER_POSITION = CAPITAL // MAX_POSITIONS
STOP_LOSS_PCT = -7.0
TRAILING_ACTIVATE_PCT = 15.0
TRAILING_STOP_PCT = 10.0
HOLD_WEEKS = 6
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
TOTAL_SELL_COST = SELL_FEE + SELL_TAX

print("\n" + "="*80)
print("模擬交易")
print("="*80)

# 為每個信號準備進場嘗試
pending_orders = {}  # stock_code -> {signal_date, signal_price, entry_attempts}
trades = []
positions = {}
cash = CAPITAL
stats = defaultdict(int)

for sig in signals:
    stock = sig['stock']

    # 獲取信號日的收盤價
    cursor.execute(
        "SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
        (stock, sig['signal_date'])
    )
    price_row = cursor.fetchone()
    if not price_row or not price_row['close_price']:
        stats['no_signal_price'] += 1
        continue

    signal_price = float(price_row['close_price'])

    pending_orders[stock] = {
        'signal_info': sig,
        'signal_price': signal_price,
        'signal_date_idx': date_index.get(sig['signal_date'], 0),
        'attempts': 0,
    }

print(f"✓ 準備 {len(pending_orders)} 個進場嘗試")

# 遍歷每個交易日
for current_idx, current_date in enumerate(all_dates):

    # 1. 檢查持倉出場
    exited = []
    for stock_code, pos in list(positions.items()):
        cursor.execute(
            "SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
            (stock_code, current_date)
        )
        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price']:
            continue

        current_price = float(price_row['close_price'])
        days_held = (datetime.strptime(current_date, '%Y%m%d') -
                     datetime.strptime(pos['buy_date'], '%Y%m%d')).days
        weeks_held = max(1, days_held // 7)

        gross_ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
        net_ret = gross_ret - TOTAL_SELL_COST * 100

        should_exit = False
        exit_reason = 'hold'
        exit_price = current_price

        # 止損
        if gross_ret <= STOP_LOSS_PCT:
            should_exit = True
            exit_reason = 'stop_loss'
            net_ret = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
            exit_price = pos['entry_price'] * (1 + STOP_LOSS_PCT / 100)

        # 追蹤止盈
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

        # 期滿
        if not should_exit and weeks_held >= HOLD_WEEKS:
            should_exit = True
            exit_reason = 'hold_period'

        if should_exit:
            pnl = pos['invested'] * net_ret / 100
            cash += pos['invested'] + pnl
            trades.append({
                'engine': pos['engine'],
                'stock': stock_code,
                'buy_date': pos['buy_date'],
                'entry_price': pos['entry_price'],
                'exit_date': current_date,
                'exit_price': exit_price,
                'weeks_held': weeks_held,
                'gross_return_pct': gross_ret,
                'net_return_pct': net_ret,
                'pnl_twd': round(pnl),
                'exit_reason': exit_reason,
            })
            exited.append(stock_code)

    for stock_code in exited:
        del positions[stock_code]

    # 2. 嘗試進場（處理待進場的訂單）
    stocks_to_remove = []

    for stock_code, order in list(pending_orders.items()):
        # 檢查是否還在進場窗口內
        # 信號日期 +3 天開始進場，最多 +8 天（5 個交易日）
        signal_idx = order['signal_date_idx']
        entry_start_idx = min(signal_idx + 3, len(all_dates) - 1)
        entry_end_idx = min(signal_idx + 8, len(all_dates) - 1)

        # 超過進場窗口
        if current_idx > entry_end_idx:
            stats['timeout'] += 1
            stocks_to_remove.append(stock_code)
            continue

        # 還沒到進場窗口
        if current_idx < entry_start_idx:
            continue

        # 在進場窗口內，檢查是否有機會進場
        if len(positions) >= MAX_POSITIONS:
            stats['max_positions'] += 1
            continue

        if stock_code in positions:
            stats['already_held'] += 1
            stocks_to_remove.append(stock_code)
            continue

        if cash < PER_POSITION:
            stats['insufficient_cash'] += 1
            continue

        # 獲取當天收盤價
        cursor.execute(
            "SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
            (stock_code, current_date)
        )
        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price']:
            continue

        current_price = float(price_row['close_price'])

        # 計算進場價：信號日收盤 vs 當日收盤的低者
        limit_price = min(order['signal_price'], current_price)

        sig = order['signal_info']
        if limit_price < sig['min_price']:
            stats['price_filter'] += 1
            continue

        # 進場成交
        shares = int(PER_POSITION / (limit_price * (1 + BUY_FEE)))
        if shares <= 0:
            continue

        invested = shares * limit_price * (1 + BUY_FEE)
        cash -= invested

        positions[stock_code] = {
            'engine': sig['engine'],
            'buy_date': current_date,
            'entry_price': limit_price,
            'shares': shares,
            'invested': invested,
            'trailing': False,
            'trailing_high': limit_price,
        }

        stocks_to_remove.append(stock_code)
        stats['entries'] += 1

    # 移除已進場或已超時的訂單
    for stock in stocks_to_remove:
        if stock in pending_orders:
            del pending_orders[stock]

# 強制平倉
last_date = all_dates[-1]
for stock_code, pos in positions.items():
    cursor.execute(
        "SELECT close_price FROM daily_prices WHERE stock_code = %s AND date = %s",
        (stock_code, last_date)
    )
    price_row = cursor.fetchone()
    exit_price = float(price_row['close_price']) if price_row and price_row['close_price'] else pos['entry_price']

    gross_ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
    net_ret = gross_ret - TOTAL_SELL_COST * 100
    pnl = pos['invested'] * net_ret / 100
    cash += pos['invested'] + pnl

    trades.append({
        'engine': pos['engine'],
        'stock': stock_code,
        'buy_date': pos['buy_date'],
        'entry_price': pos['entry_price'],
        'exit_date': last_date,
        'exit_price': exit_price,
        'weeks_held': 'open',
        'gross_return_pct': gross_ret,
        'net_return_pct': net_ret,
        'pnl_twd': round(pnl),
        'exit_reason': 'data_end',
    })

conn.close()

# 統計和報告
print(f"\n進場統計:")
print(f"  成功進場: {stats['entries']} 筆")
print(f"  超時: {stats['timeout']} 筆（超過 5 日期限）")
print(f"  其他原因未進場: {len(pending_orders)} 筆")

if trades:
    trades_df = pd.DataFrame(trades)
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl

    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100 if len(trades_df) > 0 else 0

    print("\n" + "="*80)
    print("回測結果")
    print("="*80)

    print(f"\n初始資本: {CAPITAL:,} 元")
    print(f"最終淨值: {final_equity:,} 元")
    print(f"總利潤: {total_pnl:+,} 元")
    print(f"總報酬率: {total_pnl/CAPITAL*100:+.2f}%")
    print(f"年化: {(total_pnl/CAPITAL*100)/3.27:.1f}%")

    print(f"\n交易統計:")
    print(f"  總筆數: {len(trades_df)}")
    print(f"  勝率: {win_rate:.1f}%")
    print(f"  平均回報: {trades_df['net_return_pct'].mean():+.2f}%")
    print(f"  中位數: {trades_df['net_return_pct'].median():+.2f}%")

    # 按引擎分析
    print(f"\n引擎表現:")
    for engine in ['main', 'backup']:
        e_trades = trades_df[trades_df['engine'] == engine]
        if len(e_trades) > 0:
            e_wins = (e_trades['net_return_pct'] > 0).sum()
            e_pnl = e_trades['pnl_twd'].sum()
            print(f"  {engine.upper()}: {len(e_trades)} 筆, 勝率 {e_wins/len(e_trades)*100:.1f}%, 利潤 {e_pnl:+,} 元")

    # 出場方式
    print(f"\n出場方式:")
    for reason in trades_df['exit_reason'].unique():
        r_trades = trades_df[trades_df['exit_reason'] == reason]
        avg_ret = r_trades['net_return_pct'].mean()
        pnl = r_trades['pnl_twd'].sum()
        print(f"  {reason:15s}: {len(r_trades):3d} 筆 | 平均 {avg_ret:+6.2f}% | PnL {pnl:+10,} 元")

    trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/v8/backtest_realistic_entry_results.csv', index=False)
    print(f"\n✓ 結果已保存：backtest_realistic_entry_results.csv")

print("\n" + "="*80)
print("✓ 回測完成")
print("="*80)
