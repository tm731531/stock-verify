#!/usr/bin/env python3
"""
现实双引擎回测：4个持仓限制、按时间顺序处理
总资本：500,000 TWD
最大持仓：4 个
每持仓：125,000 TWD
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict
import sys

def get_db_connection():
    """Create database connection."""
    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="tdcc",
        user="tdcc",
        password="tdcc1234"
    )

print("=" * 80)
print("现实双引擎回测：4 持仓限制、按时间顺序")
print("=" * 80)

# ============================================================================
# 第1步：数据加载
# ============================================================================

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 获取所有TDCC日期
cursor.execute("""
    SELECT DISTINCT date FROM holdings ORDER BY date
""")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_to_idx = {d: i for i, d in enumerate(all_dates)}
print(f"\n✓ 加载 {len(all_dates)} 个 TDCC 日期")

# 获取所有股票
cursor.execute("""
    SELECT DISTINCT stock_code
    FROM holdings
    WHERE stock_code NOT LIKE '00%%'
      AND ratio_400_above < 100
    ORDER BY stock_code
""")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]
print(f"✓ 加载 {len(all_stocks)} 支股票")

conn.close()

# ============================================================================
# 第2步：识别所有信号（不过滤）
# ============================================================================

print("\n" + "=" * 80)
print("第2步：信号识别")
print("=" * 80)

main_signals = []  # (stock_code, signal_date, buy_date)
backup_signals = []

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

for stock_code in all_stocks:
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings
        WHERE stock_code = %s
        ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 4:
        continue

    rows = [r for r in rows if r['total_holders'] is None or r['total_holders'] > 5]
    if len(rows) < 4:
        continue

    for i in range(3, len(rows)):
        curr_date = rows[i]['date']

        # 主引擎检查
        if (float(rows[i]['ratio_400_above'] or 0) > float(rows[i-1]['ratio_400_above'] or 0) and
            float(rows[i-1]['ratio_400_above'] or 0) > float(rows[i-2]['ratio_400_above'] or 0) and
            float(rows[i-2]['ratio_400_above'] or 0) > float(rows[i-3]['ratio_400_above'] or 0)):

            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

            if r400_chg >= 3.0:
                r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-3]['ratio_1000_above'] or 0)
                sync_ratio = r1000_chg / max(r400_chg, 0.001)

                holder_chg_pct = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                                 max(float(rows[i-3]['total_holders'] or 1), 1) * 100)

                if sync_ratio >= 0.5 and holder_chg_pct <= -2.0:
                    if i + 1 < len(rows):
                        buy_date = rows[i + 1]['date']
                        main_signals.append({
                            'stock': stock_code,
                            'signal_date': curr_date,
                            'buy_date': buy_date,
                            'engine': 'main'
                        })

        # 备用引擎检查
        holder_chg_pct = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                         max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
        r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

        if holder_chg_pct <= -15.0 and r400_chg >= 2.0:
            if i + 1 < len(rows):
                buy_date = rows[i + 1]['date']
                backup_signals.append({
                    'stock': stock_code,
                    'signal_date': curr_date,
                    'buy_date': buy_date,
                    'engine': 'backup'
                })

conn.close()

print(f"✓ 主引擎信号: {len(main_signals)}")
print(f"✓ 备用引擎信号: {len(backup_signals)}")

all_signals = main_signals + backup_signals
all_signals.sort(key=lambda x: x['buy_date'])

print(f"✓ 总信号数: {len(all_signals)}")
print(f"✓ 时间跨度: {all_signals[0]['buy_date']} ~ {all_signals[-1]['buy_date']}")

# ============================================================================
# 第3步：按时间顺序回测（4持仓限制）
# ============================================================================

print("\n" + "=" * 80)
print("第3步：按时间顺序模拟交易（4 持仓限制）")
print("=" * 80)

CAPITAL = 500_000
MAX_POSITIONS = 4
PER_POSITION = 125_000
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

# 按买入日期分组信号
signals_by_date = defaultdict(list)
for sig in all_signals:
    signals_by_date[sig['buy_date']].append(sig)

sorted_dates = sorted(signals_by_date.keys())

positions = {}  # {stock_code: position_dict}
trades = []
skipped_signals = []
cash = CAPITAL

for buy_date in sorted_dates:
    signals_today = signals_by_date[buy_date]

    # 检查持仓到期/止损的头寸
    exited_positions = []
    for stock_code, pos in list(positions.items()):
        # 计算持仓周数
        days_held = (datetime.strptime(buy_date, '%Y%m%d') -
                     datetime.strptime(pos['buy_date'], '%Y%m%d')).days
        weeks_held = max(1, days_held // 7)

        # 获取当前价格
        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (stock_code, buy_date))

        price_row = cursor.fetchone()
        current_price = float(price_row['close_price']) if price_row and price_row['close_price'] else None

        if not current_price or current_price == 0:
            continue

        # 计算回报
        gross_return_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100

        should_exit = False
        exit_reason = None

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
            if (current_price - pos['trailing_high']) / pos['trailing_high'] * 100 <= -TRAILING_STOP_PCT:
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

            exited_positions.append(stock_code)

    # 移除已出场的头寸
    for stock_code in exited_positions:
        del positions[stock_code]

    # 处理新信号（按引擎优先级：主引擎优先）
    main_signals_today = [s for s in signals_today if s['engine'] == 'main']
    backup_signals_today = [s for s in signals_today if s['engine'] == 'backup']

    for signal in main_signals_today + backup_signals_today:
        # 跳过已持仓的股票
        if signal['stock'] in positions:
            skipped_signals.append({**signal, 'reason': 'already_held'})
            continue

        # 检查是否有持仓空间
        if len(positions) >= MAX_POSITIONS:
            skipped_signals.append({**signal, 'reason': 'max_positions'})
            continue

        # 检查资金
        if cash < PER_POSITION:
            skipped_signals.append({**signal, 'reason': 'insufficient_cash'})
            continue

        # 获取买入价格
        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (signal['stock'], buy_date))

        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price'] or price_row['close_price'] == 0:
            skipped_signals.append({**signal, 'reason': 'no_price'})
            continue

        entry_price = float(price_row['close_price'])

        # 执行买入
        shares = int(PER_POSITION / (entry_price * (1 + BUY_FEE)))
        if shares <= 0:
            skipped_signals.append({**signal, 'reason': 'insufficient_shares'})
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

# 强制平仓所有剩余头寸
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
# 第4步：结果统计
# ============================================================================

print(f"\n✓ 执行交易: {len(trades)} 笔")
print(f"✓ 跳过信号: {len(skipped_signals)} 笔")
print(f"✓ 最终现金: {cash:,.0f} 元")

trades_df = pd.DataFrame(trades)

if len(trades_df) > 0:
    final_equity = cash + trades_df[trades_df['exit_reason'] == 'data_end']['pnl_twd'].sum()
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl

    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100

    print("\n" + "=" * 80)
    print("回测结果（现实条件：4 持仓限制）")
    print("=" * 80)
    print(f"\n初始资本: {CAPITAL:,.0f} 元")
    print(f"最终净值: {final_equity:,.0f} 元")
    print(f"总利润: {total_pnl:+,.0f} 元")
    print(f"总报酬率: {total_pnl/CAPITAL*100:+.2f}%")
    print(f"\n总交易数: {len(trades_df)}")
    print(f"胜率: {win_rate:.1f}% ({wins}/{len(trades_df)})")
    print(f"平均回报: {trades_df['net_return_pct'].mean():+.2f}%")
    print(f"中位数回报: {trades_df['net_return_pct'].median():+.2f}%")

    # 按引擎分析
    print("\n引擎表现:")
    for engine in ['main', 'backup']:
        engine_trades = trades_df[trades_df['engine'] == engine]
        if len(engine_trades) > 0:
            e_wins = (engine_trades['net_return_pct'] > 0).sum()
            e_win_rate = e_wins / len(engine_trades) * 100
            e_pnl = engine_trades['pnl_twd'].sum()
            print(f"\n{engine.upper()}:")
            print(f"  交易数: {len(engine_trades)}")
            print(f"  胜率: {e_win_rate:.1f}%")
            print(f"  平均回报: {engine_trades['net_return_pct'].mean():+.2f}%")
            print(f"  利润: {e_pnl:+,.0f} 元")

    # 出场分析
    print("\n出场原因:")
    exits = trades_df['exit_reason'].value_counts()
    for reason, count in exits.items():
        avg_ret = trades_df[trades_df['exit_reason'] == reason]['net_return_pct'].mean()
        print(f"  {reason:15s}: {count:3d} 笔 | 平均 {avg_ret:+.2f}%")

# 保存结果
trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/realistic_backtest_results.csv', index=False)
print(f"\n✓ 结果已保存到 realistic_backtest_results.csv")

print("\n" + "=" * 80)
print("✓ 回测完成")
print("=" * 80)
