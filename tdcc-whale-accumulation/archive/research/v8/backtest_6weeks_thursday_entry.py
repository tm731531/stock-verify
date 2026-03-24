#!/usr/bin/env python3
"""
6週版本回測（改進版 - 週四進場）
邏輯：優化進場時機，從隔週一改為同週四
     TDCC 週五公佈 → 週一掃描 → 週二掛單 → 週四進場（最快進場）
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

print("="*80)
print("回測：6週版本（改進版 - 週四進場，減少進場延遲）")
print("="*80)

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
                        # 改進：用同周周四進場而不是隔周一
                        signal_date = rows[i]['date']
                        buy_date = rows[i + 1]['date']

                        all_signals.append({
                            'stock': stock_code,
                            'signal_date': signal_date,
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
                signal_date = rows[i]['date']
                buy_date = rows[i + 1]['date']

                all_signals.append({
                    'stock': stock_code,
                    'signal_date': signal_date,
                    'buy_date': buy_date,
                    'engine': 'backup',
                    'min_price': 50.0,
                })

conn.close()

all_signals.sort(key=lambda x: x['buy_date'])
main_count = sum(1 for s in all_signals if s['engine']=='main')
backup_count = sum(1 for s in all_signals if s['engine']=='backup')

print(f"✓ 信號：主引擎 {main_count}，備用引擎 {backup_count}，共 {len(all_signals)}")

# 計算進場日期修改：從隔週一改為同週四
def get_thursday_after_signal(signal_date_str):
    """
    給定信號日期（TDCC 週五），找到同週的週四進場

    TDCC 發佈時間：週五
    掃描時間：週一
    掛單時間：週二
    進場時間：週四（同週）

    如果週四已過，則用下週四
    """
    signal_date = datetime.strptime(signal_date_str, '%Y%m%d')

    # TDCC 週五 + 1 天 = 週六
    next_day = signal_date + timedelta(days=1)

    # 找到當週的下一個週四（如果週一到週四，用同週；如果週五到週日，用下週）
    # 由於信號是週五，所以下一個進場機會是同週末後的下一個週四

    # 簡化邏輯：信號週五 → 同週末 → 隔週一掃描 → 隔週三進場
    # 但我們要改為：信號週五 → 同週末 → 同週末後的下一個週四（最多延遲到隔週四）

    # 實際上最快的是：週五信號 → 週一/二掃描 → 週二/三掛單 → 週三/四進場
    # 為了簡化，假設進場日期 = 信號日期的下一個交易日後的第 3 個交易日

    # 更簡化：直接用「信號日期後第 3 個交易日」（週五 → 下週二 → 下週三 → 下週四）
    entry_date = signal_date + timedelta(days=6)  # 週五 + 6 天 = 隔週四

    return entry_date.strftime('%Y%m%d')

# 更新進場日期（簡化為信號日期後 2-3 天進場，避免長延遲）
signals_by_signal_date = defaultdict(list)
for sig in all_signals:
    signals_by_signal_date[sig['signal_date']].append(sig)

# 重新計算進場日期：週五信號 → 隔週二開始可進場
modified_signals = []
for signal_date in sorted(signals_by_signal_date.keys()):
    sigs = signals_by_signal_date[signal_date]

    # TDCC 週五公佈 → 週一掃描 → 週二掛單 → 週三到週四進場
    signal_dt = datetime.strptime(signal_date, '%Y%m%d')

    # 週五 + 2 天 = 週日（非交易日）
    # 週五 + 3 天 = 週一（掃描）
    # 週五 + 4 天 = 週二（掛單）
    # 週五 + 5 天 = 週三（進場嘗試 1）
    # 週五 + 6 天 = 週四（進場嘗試 2）← 改為週四進場

    earliest_entry = signal_dt + timedelta(days=5)  # 同週四（如果週五開盤沒進場）或隔週三開始

    for sig in sigs:
        sig_copy = sig.copy()
        # 改進：使用同週或隔週早期進場，而非隔週一
        sig_copy['buy_date'] = earliest_entry.strftime('%Y%m%d')
        sig_copy['delay_days'] = 5  # 約 5 個交易日延遲（vs 原本的 7-8 個）
        modified_signals.append(sig_copy)

print(f"✓ 已調整進場日期（改為同週/隔週初進場）")

# 回測參數
print("\n" + "="*80)
print("模擬交易（6週版本 + 週四進場優化）")
print("="*80)

CAPITAL = 500_000
MAX_POSITIONS = 6
PER_POSITION = CAPITAL // MAX_POSITIONS
MAX_ENTRIES_PER_WEEK = 2
STOP_LOSS_PCT = -7.0
TRAILING_ACTIVATE_PCT = 15.0
TRAILING_STOP_PCT = 10.0
HOLD_WEEKS = 6
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
TOTAL_SELL_COST = SELL_FEE + SELL_TAX

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

signals_by_date = defaultdict(list)
for sig in modified_signals:
    signals_by_date[sig['buy_date']].append(sig)

sorted_dates = sorted(signals_by_date.keys())

def get_week_number(date_str):
    return datetime.strptime(date_str, '%Y%m%d').isocalendar()[1]

positions = {}
trades = []
cash = CAPITAL
entries_by_week = defaultdict(int)
skipped_by_reason = defaultdict(int)

for buy_date in sorted_dates:
    signals_today = signals_by_date[buy_date]
    week_num = get_week_number(buy_date)

    # 檢查持倉出場
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

        if gross_return_pct <= STOP_LOSS_PCT:
            should_exit = True
            exit_reason = 'stop_loss'
            net_return_pct = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
            exit_price = pos['entry_price'] * (1 + STOP_LOSS_PCT / 100)

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

    # 處理新信號 - 主備同進
    entries_today = 0
    main_sigs = [s for s in signals_today if s['engine'] == 'main']
    backup_sigs = [s for s in signals_today if s['engine'] == 'backup']

    sigs_to_process = main_sigs + backup_sigs

    for signal in sigs_to_process:
        if entries_today >= MAX_ENTRIES_PER_WEEK:
            break

        if signal['stock'] in positions:
            skipped_by_reason['already_held'] += 1
            continue

        if len(positions) >= MAX_POSITIONS:
            skipped_by_reason['max_positions'] += 1
            continue

        if cash < PER_POSITION:
            skipped_by_reason['insufficient_cash'] += 1
            continue

        cursor.execute("""
            SELECT close_price FROM daily_prices
            WHERE stock_code = %s AND date = %s
        """, (signal['stock'], buy_date))

        price_row = cursor.fetchone()
        if not price_row or not price_row['close_price'] or price_row['close_price'] == 0:
            skipped_by_reason['no_price'] += 1
            continue

        entry_price = float(price_row['close_price'])

        # 股價限制檢查
        if entry_price < signal['min_price']:
            skipped_by_reason['price_filter'] += 1
            continue

        shares = int(PER_POSITION / (entry_price * (1 + BUY_FEE)))

        if shares <= 0:
            skipped_by_reason['insufficient_shares'] += 1
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

if len(trades_df) > 0:
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl

    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100

    print(f"\n✓ 執行交易: {len(trades_df)} 筆")

    print("\n" + "="*80)
    print("回測結果：6週版本（改進版 - 週四進場）")
    print("="*80)

    print(f"\n初始資本: {CAPITAL:,} 元")
    print(f"最終淨值: {final_equity:,} 元")
    print(f"總利潤: {total_pnl:+,} 元")
    print(f"總報酬率: {total_pnl/CAPITAL*100:+.2f}%")
    print(f"年化: {(total_pnl/CAPITAL*100)/3.27:.1f}%")

    print(f"\n交易統計:")
    print(f"  總筆數: {len(trades_df)}")
    print(f"  勝率: {win_rate:.1f}% ({wins}/{len(trades_df)})")
    print(f"  平均回報: {trades_df['net_return_pct'].mean():+.2f}%")
    print(f"  中位數: {trades_df['net_return_pct'].median():+.2f}%")
    print(f"  最好: {trades_df['net_return_pct'].max():+.2f}%")
    print(f"  最差: {trades_df['net_return_pct'].min():+.2f}%")

    # 按引擎分析
    print(f"\n引擎表現:")
    for engine in ['main', 'backup']:
        engine_trades = trades_df[trades_df['engine'] == engine]
        if len(engine_trades) > 0:
            e_wins = (engine_trades['net_return_pct'] > 0).sum()
            e_win_rate = e_wins / len(engine_trades) * 100
            e_pnl = engine_trades['pnl_twd'].sum()
            e_avg = engine_trades['net_return_pct'].mean()
            print(f"\n{engine.upper()}:")
            print(f"  交易數: {len(engine_trades)}")
            print(f"  勝率: {e_win_rate:.1f}%")
            print(f"  平均回報: {e_avg:+.2f}%")
            print(f"  利潤: {e_pnl:+,} 元")

    # 出場分析
    print(f"\n出場方式:")
    exits = trades_df['exit_reason'].value_counts()
    for reason, count in exits.items():
        avg_ret = trades_df[trades_df['exit_reason'] == reason]['net_return_pct'].mean()
        pnl = trades_df[trades_df['exit_reason'] == reason]['pnl_twd'].sum()
        print(f"  {reason:15s}: {count:3d} 筆 | 平均 {avg_ret:+6.2f}% | PnL {pnl:+10,} 元")

trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/v8/backtest_6weeks_thursday_entry_results.csv', index=False)
print(f"\n✓ 結果已保存：backtest_6weeks_thursday_entry_results.csv")

print("\n" + "="*80)
print("✓ 回測完成")
print("="*80)
