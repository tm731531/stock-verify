#!/usr/bin/env python3
"""
全版本對比回測：4週、6週、7週、8週、13週
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

def run_backtest(hold_weeks):
    """執行指定持有期限的回測"""

    print(f"\n{'='*80}")
    print(f"回測：{hold_weeks}週持仓版本")
    print(f"{'='*80}")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 加載數據
    cursor.execute("SELECT DISTINCT date FROM holdings ORDER BY date")
    all_dates = sorted([row['date'] for row in cursor.fetchall()])

    cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' AND ratio_400_above < 100 ORDER BY stock_code")
    all_stocks = [row['stock_code'] for row in cursor.fetchall()]

    print(f"✓ 加載 {len(all_dates)} 個日期，{len(all_stocks)} 支股票")

    # 識別信號
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
                                'min_price': 300.0,
                            })

            # 備用引擎
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
                        'min_price': 50.0,
                    })

    all_signals.sort(key=lambda x: x['buy_date'])
    main_count = sum(1 for s in all_signals if s['engine']=='main')
    backup_count = sum(1 for s in all_signals if s['engine']=='backup')

    print(f"✓ 信號：主引擎 {main_count}，備用引擎 {backup_count}，共 {len(all_signals)}")

    # 回測參數
    CAPITAL = 500_000
    MAX_POSITIONS = 6
    PER_POSITION = CAPITAL // MAX_POSITIONS
    MAX_ENTRIES_PER_WEEK = 2
    STOP_LOSS_PCT = -7.0
    TRAILING_ACTIVATE_PCT = 15.0
    TRAILING_STOP_PCT = 10.0
    BUY_FEE = 0.001425
    SELL_FEE = 0.001425
    SELL_TAX = 0.003
    TOTAL_SELL_COST = SELL_FEE + SELL_TAX

    signals_by_date = defaultdict(list)
    for sig in all_signals:
        signals_by_date[sig['buy_date']].append(sig)

    sorted_dates = sorted(signals_by_date.keys())

    def get_week_number(date_str):
        return datetime.strptime(date_str, '%Y%m%d').isocalendar()[1]

    positions = {}
    trades = []
    cash = CAPITAL

    # 時間序列回測
    for buy_date in sorted_dates:
        signals_today = signals_by_date[buy_date]

        # 檢查持仓出場
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

            # 止損
            if gross_return_pct <= STOP_LOSS_PCT:
                should_exit = True
                exit_reason = 'stop_loss'
                net_return_pct = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
                exit_price = pos['entry_price'] * (1 + STOP_LOSS_PCT / 100)

            # 追蹤止盈
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

            # 持仓期限
            if not should_exit and weeks_held >= hold_weeks:
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

        # 進場
        entries_today = 0
        main_sigs = [s for s in signals_today if s['engine'] == 'main']
        backup_sigs = [s for s in signals_today if s['engine'] == 'backup']

        for signal in main_sigs + backup_sigs:
            if entries_today >= MAX_ENTRIES_PER_WEEK:
                break

            if signal['stock'] in positions:
                continue

            if len(positions) >= MAX_POSITIONS:
                continue

            if cash < PER_POSITION:
                continue

            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (signal['stock'], buy_date))

            price_row = cursor.fetchone()
            if not price_row or not price_row['close_price'] or price_row['close_price'] == 0:
                continue

            entry_price = float(price_row['close_price'])

            # 股價限制
            if entry_price < signal['min_price']:
                continue

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

    # 強制平倉
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

    # 結果統計
    trades_df = pd.DataFrame(trades)

    if len(trades_df) == 0:
        return None

    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl
    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100

    # 按出場方式分類
    exits_stats = {}
    for reason in ['hold_period', 'trailing_stop', 'stop_loss', 'data_end']:
        reason_trades = trades_df[trades_df['exit_reason'] == reason]
        if len(reason_trades) > 0:
            exits_stats[reason] = {
                'count': len(reason_trades),
                'avg_return': reason_trades['net_return_pct'].mean(),
                'pnl': reason_trades['pnl_twd'].sum(),
            }

    # 按引擎分類
    engine_stats = {}
    for engine in ['main', 'backup']:
        engine_trades = trades_df[trades_df['engine'] == engine]
        if len(engine_trades) > 0:
            engine_stats[engine] = {
                'count': len(engine_trades),
                'win_rate': (engine_trades['net_return_pct'] > 0).sum() / len(engine_trades) * 100,
                'avg_return': engine_trades['net_return_pct'].mean(),
                'pnl': engine_trades['pnl_twd'].sum(),
            }

    result = {
        'hold_weeks': hold_weeks,
        'total_trades': len(trades_df),
        'total_pnl': total_pnl,
        'final_equity': final_equity,
        'total_return_pct': total_pnl / CAPITAL * 100,
        'annualized': (total_pnl / CAPITAL * 100) / 3.27,
        'win_rate': win_rate,
        'avg_return': trades_df['net_return_pct'].mean(),
        'median_return': trades_df['net_return_pct'].median(),
        'best_trade': trades_df['net_return_pct'].max(),
        'worst_trade': trades_df['net_return_pct'].min(),
        'exits_stats': exits_stats,
        'engine_stats': engine_stats,
        'trades_df': trades_df,
    }

    return result

# 執行所有版本
versions = [4, 6, 7, 8, 13]
all_results = {}

for weeks in versions:
    result = run_backtest(weeks)
    if result:
        all_results[weeks] = result

        print(f"\n📊 {weeks}週版本結果：")
        print(f"  交易數：{result['total_trades']} 筆")
        print(f"  總報酬：{result['total_return_pct']:+.2f}%（{result['total_pnl']:+,} 元）")
        print(f"  年化：{result['annualized']:.1f}%")
        print(f"  勝率：{result['win_rate']:.1f}%")
        print(f"  平均報酬：{result['avg_return']:+.2f}%")
        print(f"  中位數：{result['median_return']:+.2f}%")

# 完整對比
print(f"\n{'='*80}")
print("完整版本對比")
print(f"{'='*80}\n")

comparison_data = []
for weeks in sorted(all_results.keys()):
    r = all_results[weeks]
    comparison_data.append({
        '週數': weeks,
        '交易數': r['total_trades'],
        '總報酬%': f"{r['total_return_pct']:+.2f}%",
        '年化%': f"{r['annualized']:.1f}%",
        '勝率%': f"{r['win_rate']:.1f}%",
        '平均%': f"{r['avg_return']:+.2f}%",
        '中位數%': f"{r['median_return']:+.2f}%",
    })

comparison_df = pd.DataFrame(comparison_data)
print(comparison_df.to_string(index=False))

# 詳細分析
print(f"\n{'='*80}")
print("詳細出場方式分析")
print(f"{'='*80}\n")

for weeks in sorted(all_results.keys()):
    r = all_results[weeks]
    print(f"\n{weeks}週版本：")
    for reason, stats in sorted(r['exits_stats'].items()):
        print(f"  {reason:15s}: {stats['count']:3d} 筆 | 平均 {stats['avg_return']:+6.2f}% | PnL {stats['pnl']:+10,} 元")

# 引擎分析
print(f"\n{'='*80}")
print("引擎表現分析")
print(f"{'='*80}\n")

for weeks in sorted(all_results.keys()):
    r = all_results[weeks]
    print(f"\n{weeks}週版本：")
    for engine, stats in sorted(r['engine_stats'].items()):
        print(f"  {engine.upper():6s}: {stats['count']:3d} 筆 | 勝率 {stats['win_rate']:5.1f}% | 平均 {stats['avg_return']:+6.2f}% | PnL {stats['pnl']:+10,} 元")

# 保存結果
print(f"\n{'='*80}")
print("保存結果檔案")
print(f"{'='*80}\n")

for weeks, result in all_results.items():
    csv_path = f'/home/tom/stock-verify/tdcc-whale-accumulation/backtest_{weeks}weeks_results.csv'
    result['trades_df'].to_csv(csv_path, index=False)
    print(f"✓ {weeks}週版本已保存: {csv_path}")

print("\n✓ 全版本回測完成")
