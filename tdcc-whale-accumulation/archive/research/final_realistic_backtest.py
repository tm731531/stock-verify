#!/usr/bin/env python3
"""
最终现实回测：4持仓 + 每周最多2笔进场
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="tdcc",
        user="tdcc",
        password="tdcc1234"
    )

print("=" * 80)
print("最终现实回测：4持仓 + 每周最多2笔")
print("=" * 80)

# ============================================================================
# 第1步：数据加载和信号识别
# ============================================================================

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

cursor.execute("SELECT DISTINCT date FROM holdings ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_to_idx = {d: i for i, d in enumerate(all_dates)}

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' AND ratio_400_above < 100 ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

print(f"\n✓ 加载 {len(all_dates)} 个 TDCC 日期")
print(f"✓ 加载 {len(all_stocks)} 支股票")

# 识别所有信号
all_signals = []

for stock_code in all_stocks:
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings WHERE stock_code = %s ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 4:
        continue
    rows = [r for r in rows if r['total_holders'] is None or r['total_holders'] > 5]
    if len(rows) < 4:
        continue

    for i in range(3, len(rows)):
        curr_date = rows[i]['date']

        # 主引擎
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
                    if i + 1 < len(rows):
                        buy_date = rows[i + 1]['date']
                        all_signals.append({
                            'stock': stock_code,
                            'buy_date': buy_date,
                            'engine': 'main',
                            'r400_chg': r400_chg,
                        })

        # 备用引擎
        holder_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                     max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
        r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

        if holder_chg <= -15.0 and r400_chg >= 2.0:
            if i + 1 < len(rows):
                buy_date = rows[i + 1]['date']
                all_signals.append({
                    'stock': stock_code,
                    'buy_date': buy_date,
                    'engine': 'backup',
                    'holder_exodus': holder_chg,
                })

conn.close()

all_signals.sort(key=lambda x: x['buy_date'])
print(f"\n✓ 主引擎信号: {sum(1 for s in all_signals if s['engine']=='main')}")
print(f"✓ 备用引擎信号: {sum(1 for s in all_signals if s['engine']=='backup')}")
print(f"✓ 总信号数: {len(all_signals)}")

# ============================================================================
# 第2步：按时间顺序回测（4持仓 + 每周2笔限制）
# ============================================================================

print("\n" + "=" * 80)
print("第2步：模拟交易（4持仓 + 每周最多2笔）")
print("=" * 80)

CAPITAL = 500_000
MAX_POSITIONS = 4
PER_POSITION = 125_000
MAX_ENTRIES_PER_WEEK = 2
STOP_LOSS_PCT = -7.0
TRAILING_ACTIVATE_PCT = 15.0
TRAILING_STOP_PCT = 10.0
HOLD_WEEKS = 4
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
TOTAL_SELL_COST = SELL_FEE + SELL_TAX

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 按买入日期分组
signals_by_date = defaultdict(list)
for sig in all_signals:
    signals_by_date[sig['buy_date']].append(sig)

sorted_dates = sorted(signals_by_date.keys())

# 计算周号（ISO周）
def get_week_number(date_str):
    return datetime.strptime(date_str, '%Y%m%d').isocalendar()[1]

positions = {}
trades = []
cash = CAPITAL
entries_by_week = defaultdict(int)  # 周号 -> 该周进场笔数

for buy_date in sorted_dates:
    signals_today = signals_by_date[buy_date]
    week_num = get_week_number(buy_date)

    # 检查持仓是否应该出场
    exited = []
    for stock_code, pos in list(positions.items()):
        days_held = (datetime.strptime(buy_date, '%Y%m%d') -
                     datetime.strptime(pos['buy_date'], '%Y%m%d')).days
        weeks_held = max(1, days_held // 7)

        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (stock_code, buy_date))

        price_row = cursor.fetchone()
        current_price = float(price_row['close_price']) if price_row and price_row['close_price'] else None

        if not current_price or current_price == 0:
            continue

        gross_return_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100

        should_exit = False
        exit_reason = None
        exit_price = current_price

        # 止损检查
        if gross_return_pct <= STOP_LOSS_PCT:
            should_exit = True
            exit_reason = 'stop_loss'
            net_return_pct = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
            exit_price = pos['entry_price'] * (1 + STOP_LOSS_PCT / 100)

        # 追踪止盈检查
        elif gross_return_pct >= TRAILING_ACTIVATE_PCT and not pos.get('trailing_activated'):
            pos['trailing_activated'] = True
            pos['trailing_high'] = current_price

        if pos.get('trailing_activated'):
            pullback = (current_price - pos['trailing_high']) / pos['trailing_high'] * 100
            if pullback <= -TRAILING_STOP_PCT:
                should_exit = True
                exit_reason = 'trailing_stop'
                net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100
                exit_price = current_price
            else:
                pos['trailing_high'] = max(pos['trailing_high'], current_price)

        # 持仓期限检查
        if not should_exit and weeks_held >= HOLD_WEEKS:
            should_exit = True
            exit_reason = 'hold_period'
            net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100
            exit_price = current_price

        if should_exit:
            pnl = pos['invested'] * net_return_pct / 100
            cash += pos['invested'] + pnl

            trades.append({
                'engine': pos['engine'],
                'stock': stock_code,
                'buy_date': pos['buy_date'],
                'entry_price': pos['entry_price'],
                'exit_date': buy_date,
                'exit_price': exit_price,
                'weeks_held': weeks_held,
                'gross_return_pct': gross_return_pct,
                'net_return_pct': net_return_pct,
                'pnl_twd': round(pnl),
                'exit_reason': exit_reason,
            })

            exited.append(stock_code)

    for stock_code in exited:
        del positions[stock_code]

    # 处理新信号（受周限制）
    entries_today = 0

    # 优先级：主引擎优先
    main_sigs = [s for s in signals_today if s['engine'] == 'main']
    backup_sigs = [s for s in signals_today if s['engine'] == 'backup']

    for signal in main_sigs + backup_sigs:
        # 周限制检查
        if entries_today >= MAX_ENTRIES_PER_WEEK:
            break

        # 已持仓检查
        if signal['stock'] in positions:
            continue

        # 持仓满检查
        if len(positions) >= MAX_POSITIONS:
            continue

        # 资金检查
        if cash < PER_POSITION:
            continue

        # 获取买入价格
        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (signal['stock'], buy_date))

        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price'] or price_row['close_price'] == 0:
            continue

        entry_price = float(price_row['close_price'])
        shares = int(PER_POSITION / (entry_price * (1 + BUY_FEE)))

        if shares <= 0:
            continue

        invested = shares * entry_price * (1 + BUY_FEE)
        cash -= invested

        positions[signal['stock']] = {
            'engine': signal['engine'],
            'buy_date': buy_date,
            'entry_price': entry_price,
            'shares': shares,
            'invested': invested,
            'trailing_activated': False,
            'trailing_high': entry_price,
        }

        entries_today += 1

    entries_by_week[week_num] += entries_today

# 强制平仓
last_date = sorted_dates[-1]
for stock_code, pos in positions.items():
    cursor.execute("""
        SELECT close_price FROM daily_prices
        WHERE stock_code = %s AND date <= %s
        ORDER BY date DESC LIMIT 1
    """, (stock_code, last_date))

    price_row = cursor.fetchone()
    exit_price = float(price_row['close_price']) if price_row and price_row['close_price'] else pos['entry_price']

    gross_return_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
    net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100
    pnl = pos['invested'] * net_return_pct / 100
    cash += pos['invested'] + pnl

    trades.append({
        'engine': pos['engine'],
        'stock': stock_code,
        'buy_date': pos['buy_date'],
        'entry_price': pos['entry_price'],
        'exit_date': last_date,
        'exit_price': exit_price,
        'weeks_held': 'open',
        'gross_return_pct': gross_return_pct,
        'net_return_pct': net_return_pct,
        'pnl_twd': round(pnl),
        'exit_reason': 'data_end',
    })

conn.close()

# ============================================================================
# 第3步：结果统计
# ============================================================================

print(f"\n✓ 执行交易: {len(trades)} 笔")
print(f"✓ 最终现金: {cash:,.0f} 元")

trades_df = pd.DataFrame(trades)

if len(trades_df) > 0:
    final_equity = cash + sum(t['pnl_twd'] for t in trades if t['exit_reason'] != 'data_end')
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl

    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100

    print("\n" + "=" * 80)
    print("回测结果（4持仓 + 每周2笔）")
    print("=" * 80)
    print(f"\n初始资本: {CAPITAL:,} 元")
    print(f"最终净值: {final_equity:,} 元")
    print(f"总利润: {total_pnl:+,} 元")
    print(f"总报酬率: {total_pnl/CAPITAL*100:+.2f}%")
    print(f"年化: {(total_pnl/CAPITAL*100)/3.27:.1f}%")

    print(f"\n总交易数: {len(trades_df)}")
    print(f"胜率: {win_rate:.1f}% ({wins}/{len(trades_df)})")
    print(f"平均回报: {trades_df['net_return_pct'].mean():+.2f}%")
    print(f"中位数回报: {trades_df['net_return_pct'].median():+.2f}%")
    print(f"最好: {trades_df['net_return_pct'].max():+.2f}%")
    print(f"最差: {trades_df['net_return_pct'].min():+.2f}%")

    print(f"\n每周进场统计:")
    weekly_entries = sorted(entries_by_week.items())
    if weekly_entries:
        avg_entries = np.mean([count for _, count in weekly_entries])
        max_entries = max(count for _, count in weekly_entries)
        print(f"  平均每周: {avg_entries:.1f} 笔")
        print(f"  最多一周: {max_entries} 笔")
        print(f"  限制检查: {sum(1 for _, c in weekly_entries if c >= MAX_ENTRIES_PER_WEEK)} 周达到上限")

    # 按引擎分析
    print(f"\n引擎表现:")
    for engine in ['main', 'backup']:
        engine_trades = trades_df[trades_df['engine'] == engine]
        if len(engine_trades) > 0:
            e_wins = (engine_trades['net_return_pct'] > 0).sum()
            e_win_rate = e_wins / len(engine_trades) * 100
            e_pnl = engine_trades['pnl_twd'].sum()
            e_avg = engine_trades['net_return_pct'].mean()
            print(f"\n{engine.upper()}:")
            print(f"  交易数: {len(engine_trades)}")
            print(f"  胜率: {e_win_rate:.1f}%")
            print(f"  平均回报: {e_avg:+.2f}%")
            print(f"  利润: {e_pnl:+,} 元")

    # 出场分析
    print(f"\n出场原因:")
    exits = trades_df['exit_reason'].value_counts()
    for reason, count in exits.items():
        avg_ret = trades_df[trades_df['exit_reason'] == reason]['net_return_pct'].mean()
        pnl = trades_df[trades_df['exit_reason'] == reason]['pnl_twd'].sum()
        print(f"  {reason:15s}: {count:3d} 笔 | 平均 {avg_ret:+6.2f}% | PnL {pnl:+10,}")

trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/final_backtest_results.csv', index=False)
print(f"\n✓ 结果已保存")

print("\n" + "=" * 80)
print("✓ 回测完成")
print("=" * 80)
