#!/usr/bin/env python3
"""
6週版本回測 - 實盤進場邏輯（限價單 + 5日期限）

邏輯：
  1. 週五抓 TDCC 數據 → 識別信號
  2. 週六日收整進場清單
  3. 週三開始掛單：用「上週五收盤價」和「進場日開盤價」的低者
  4. 5 個交易日內沒成交 → 放棄這支股票

這更接近實盤的情況：
  - 不會在信號當天就進場（股票可能早飛掉）
  - 用限價單，不會被拉高
  - 有明確的「放棄時限」，不會被套很久
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
print("回測：6週版本（實盤進場邏輯 - 限價單 + 5日期限）")
print("="*80)

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 加載數據
cursor.execute("SELECT DISTINCT date FROM holdings ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' AND ratio_400_above < 100 ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

print(f"✓ 加載 {len(all_dates)} 個日期，{len(all_stocks)} 支股票")

# 識別信號（和原版一樣）
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
                    signal_date = rows[i]['date']

                    all_signals.append({
                        'stock': stock_code,
                        'signal_date': signal_date,
                        'engine': 'main',
                        'min_price': 300.0,
                    })

        # 備用引擎
        holder_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                     max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
        r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

        if holder_chg <= -15.0 and r400_chg >= 2.0:
            signal_date = rows[i]['date']

            all_signals.append({
                'stock': stock_code,
                'signal_date': signal_date,
                'engine': 'backup',
                'min_price': 50.0,
            })

conn.close()

print(f"✓ 信號：{len(all_signals)} 個")

# 關鍵改動：計算進場日期和進場價格
def get_entry_window_and_signal_price(signal_date_str, conn):
    """
    給定信號日期（TDCC 週五）：
    1. 找到信號日期的收盤價（上週五的價格）
    2. 計算進場窗口：從週三開始，5 個交易日內
    3. 返回 (signal_price, entry_start_date, entry_window_days)
    """
    signal_dt = datetime.strptime(signal_date_str, '%Y%m%d')
    signal_weekday = signal_dt.weekday()  # 0=Mon, 4=Fri

    # 計算進場窗口：信號週五之後的週三開始
    # 週五 + 2 天 = 週日（非交易日）
    # 週五 + 3 天 = 週一
    # 週五 + 4 天 = 週二
    # 週五 + 5 天 = 週三 ← 進場窗口開始
    entry_start = signal_dt + timedelta(days=5)
    entry_end = entry_start + timedelta(days=6)  # 5 個交易日 ≈ 週三到隔週二

    return entry_start, entry_end

# 準備每個信號的進場窗口
signals_with_windows = []
for sig in all_signals:
    entry_start, entry_end = get_entry_window_and_signal_price(sig['signal_date'], conn)
    sig['entry_start'] = entry_start.strftime('%Y%m%d')
    sig['entry_end'] = entry_end.strftime('%Y%m%d')
    signals_with_windows.append(sig)

print(f"✓ 計算進場窗口（週三開始，5 個交易日）")

# 回測參數
print("\n" + "="*80)
print("模擬交易（6週版本 + 實盤進場邏輯）")
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

# 加載所有日期，用於查詢股價
cursor.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
all_trading_dates = sorted([row['date'] for row in cursor.fetchall()])

# 建立日期到索引的映射，加快查詢
trading_date_index = {d: i for i, d in enumerate(all_trading_dates)}

def get_next_trading_days(start_date_str, count):
    """取得從某日期開始的下 count 個交易日"""
    if start_date_str not in trading_date_index:
        return []

    start_idx = trading_date_index[start_date_str]
    end_idx = min(start_idx + count, len(all_trading_dates))
    return all_trading_dates[start_idx:end_idx]

def get_price_at_date(stock_code, date_str):
    """取得某日期的收盤價"""
    cursor.execute("""
        SELECT close_price FROM daily_prices
        WHERE stock_code = %s AND date = %s
    """, (stock_code, date_str))

    row = cursor.fetchone()
    if not row:
        return None

    return float(row['close_price']) if row['close_price'] else None

# 核心回測邏輯
positions = {}
pending_entries = {}  # 待進場的信號：stock -> {signal_info, attempt_dates, signal_price}
trades = []
cash = CAPITAL
entries_by_week = defaultdict(int)
skipped_by_reason = defaultdict(int)
failed_entries = defaultdict(int)  # 統計失敗的進場嘗試

# 準備所有進場嘗試
for sig in signals_with_windows:
    stock = sig['stock']

    # 獲得信號日期的收盤價
    signal_price = get_price_at_date(stock, sig['signal_date'])

    if not signal_price or signal_price == 0:
        skipped_by_reason['no_signal_price'] += 1
        continue

    # 獲得進場窗口內的所有交易日
    entry_dates = get_next_trading_days(sig['entry_start'], 5)

    if not entry_dates:
        skipped_by_reason['no_entry_dates'] += 1
        continue

    pending_entries[stock] = {
        'signal_info': sig,
        'signal_price': signal_price,
        'entry_dates': entry_dates,
        'attempt_index': 0,
    }

print(f"✓ 準備 {len(pending_entries)} 個進場嘗試")
print(f"✗ 信號找不到價格: {skipped_by_reason['no_signal_price']} 個")
print(f"✗ 信號找不到進場日期: {skipped_by_reason['no_entry_dates']} 個")

# 按進場日期遍歷所有交易日
current_date_idx = 0
while current_date_idx < len(all_trading_dates) and (positions or pending_entries):
    buy_date = all_trading_dates[current_date_idx]
    week_num = datetime.strptime(buy_date, '%Y%m%d').isocalendar()[1]

    # 1. 檢查持倉出場
    exited = []
    for stock_code, pos in list(positions.items()):
        current_price = get_price_at_date(stock_code, buy_date)

        if not current_price or current_price == 0:
            current_date_idx += 1
            continue

        days_held = (datetime.strptime(buy_date, '%Y%m%d') -
                     datetime.strptime(pos['buy_date'], '%Y%m%d')).days
        weeks_held = max(1, days_held // 7)

        gross_return_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100

        should_exit = False
        exit_reason = None
        exit_price = current_price
        net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100

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

        # 期滿
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
                'signal_date': pos['signal_date'],
            })

            exited.append(stock_code)

    for stock_code in exited:
        del positions[stock_code]

    # 2. 嘗試進場（處理待進場的信號）
    stocks_to_remove = []
    for stock_code, entry_info in pending_entries.items():
        attempt_idx = entry_info['attempt_index']

        # 檢查是否超過 5 個交易日
        if attempt_idx >= len(entry_info['entry_dates']):
            # 超過期限，放棄
            failed_entries[stock_code] += 1
            skipped_by_reason['entry_timeout'] += 1
            stocks_to_remove.append(stock_code)
            continue

        current_attempt_date = entry_info['entry_dates'][attempt_idx]

        # 如果還沒到進場日期，跳過
        if buy_date < current_attempt_date:
            entry_info['attempt_index'] += 1
            continue

        # 到了進場日期，取得當天收盤價
        attempt_price = get_price_at_date(stock_code, current_attempt_date)

        if not attempt_price or attempt_price == 0:
            entry_info['attempt_index'] += 1
            continue

        # 計算掛單價：上週五收盤 vs 進場日收盤的低者
        # （因為數據庫只有收盤價，用低價進場的邏輯）
        signal_price = entry_info['signal_price']
        limit_price = min(signal_price, attempt_price)

        # 檢查是否能進場
        if len(positions) >= MAX_POSITIONS:
            skipped_by_reason['max_positions'] += 1
            entry_info['attempt_index'] += 1
            continue

        if stock_code in positions:
            skipped_by_reason['already_held'] += 1
            stocks_to_remove.append(stock_code)
            continue

        if cash < PER_POSITION:
            skipped_by_reason['insufficient_cash'] += 1
            entry_info['attempt_index'] += 1
            continue

        sig = entry_info['signal_info']
        if limit_price < sig['min_price']:
            skipped_by_reason['price_filter'] += 1
            entry_info['attempt_index'] += 1
            continue

        # 進場成交
        shares = int(PER_POSITION / (limit_price * (1 + BUY_FEE)))

        if shares <= 0:
            skipped_by_reason['insufficient_shares'] += 1
            entry_info['attempt_index'] += 1
            continue

        invested = shares * limit_price * (1 + BUY_FEE)
        cash -= invested

        positions[stock_code] = {
            'engine': sig['engine'],
            'buy_date': current_attempt_date,
            'entry_price': limit_price,
            'shares': shares,
            'invested': invested,
            'trailing_activated': False,
            'trailing_high': limit_price,
            'signal_date': sig['signal_date'],
        }

        stocks_to_remove.append(stock_code)
        entries_by_week[week_num] += 1

    # 移除已進場或已放棄的信號
    for stock in stocks_to_remove:
        if stock in pending_entries:
            del pending_entries[stock]

    current_date_idx += 1

# 強制平倉
if positions:
    last_date = all_trading_dates[-1]
    for stock_code, pos in positions.items():
        exit_price = get_price_at_date(stock_code, last_date)
        if not exit_price:
            exit_price = pos['entry_price']

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
            'signal_date': pos['signal_date'],
        })

conn.close()

# 結果統計
trades_df = pd.DataFrame(trades)

print(f"\n進場結果統計:")
print(f"  嘗試進場: {len(pending_entries) + len(failed_entries)} 筆")
print(f"  成功進場: {len(trades_df)} 筆")
print(f"  失敗進場: {len(failed_entries)} 筆（超過 5 日期限）")

if len(trades_df) > 0:
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = CAPITAL + total_pnl

    wins = (trades_df['net_return_pct'] > 0).sum()
    win_rate = wins / len(trades_df) * 100

    print(f"\n✓ 執行交易: {len(trades_df)} 筆")

    print("\n" + "="*80)
    print("回測結果：6週版本（實盤進場邏輯）")
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
            print(f"\n  {engine.upper()}:")
            print(f"    交易數: {len(engine_trades)}")
            print(f"    勝率: {e_win_rate:.1f}%")
            print(f"    平均回報: {e_avg:+.2f}%")
            print(f"    利潤: {e_pnl:+,} 元")

    # 出場分析
    print(f"\n出場方式:")
    exits = trades_df['exit_reason'].value_counts()
    for reason, count in exits.items():
        avg_ret = trades_df[trades_df['exit_reason'] == reason]['net_return_pct'].mean()
        pnl = trades_df[trades_df['exit_reason'] == reason]['pnl_twd'].sum()
        print(f"  {reason:15s}: {count:3d} 筆 | 平均 {avg_ret:+6.2f}% | PnL {pnl:+10,} 元")

    # 進場困難統計
    print(f"\n進場困難統計（為什麼沒有更多交易）:")
    for reason, count in sorted(skipped_by_reason.items(), key=lambda x: -x[1])[:5]:
        print(f"  {reason:20s}: {count:4d} 筆")

trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/v8/backtest_realistic_entry_results.csv', index=False)
print(f"\n✓ 結果已保存：backtest_realistic_entry_results.csv")

print("\n" + "="*80)
print("✓ 回測完成")
print("="*80)
