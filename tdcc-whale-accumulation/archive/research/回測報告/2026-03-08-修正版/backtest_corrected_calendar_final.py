#!/usr/bin/env python3
"""
修正版回測 - 正確的日曆天數實現

關鍵修正：
1. 日曆天數 >= max_hold_calendar_days 時無條件出場
2. 不能因為沒有價格數據就延後出場檢查
3. 區分「應該出場」和「何時出場」：
   - 應該出場：calendar_days >= max_hold_calendar_days
   - 何時出場：有價格數據時執行
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
print("v7 策略回測 - 正確的日曆天數實現 (FINAL)")
print("="*80)

# ================================================================================
# 全局配置
# ================================================================================

CAPITAL = 500_000
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
STOP_LOSS_PCT = -7.0

# 加載數據
print("\n加載數據...")
conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 全週期數據（限制 2022-2025）
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
    ORDER BY date
""")
all_dates_full = sorted([row['date'] for row in cursor.fetchall()])
date_index_full = {d: i for i, d in enumerate(all_dates_full)}

# 2023 年數據
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20230101' AND date <= '20231231'
    ORDER BY date
""")
all_dates_2023 = sorted([row['date'] for row in cursor.fetchall()])
date_index_2023 = {d: i for i, d in enumerate(all_dates_2023)}

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%'")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

print(f"✓ 全週期：{len(all_dates_full)} 個交易日")
print(f"✓ 2023年：{len(all_dates_2023)} 個交易日")
print(f"✓ {len(all_stocks)} 支股票")

# ================================================================================
# 掃描信號函數
# ================================================================================

def scan_main_engine(date_range=None):
    """掃描主引擎訊號"""
    signals = []
    date_filter = ""
    if date_range == '2023':
        date_filter = "AND date >= '20230101' AND date <= '20231231'"

    for stock_code in all_stocks:
        cursor.execute(f"""
            SELECT date, ratio_400_above, ratio_1000_above, total_holders
            FROM holdings WHERE stock_code = %s {date_filter}
            ORDER BY date
        """, (stock_code,))

        rows = list(cursor.fetchall())
        if len(rows) < 4:
            continue

        for i in range(3, len(rows)):
            streak = 0
            for j in range(i, 0, -1):
                if float(rows[j]['ratio_400_above'] or 0) > float(rows[j-1]['ratio_400_above'] or 0):
                    streak += 1
                else:
                    break

            if streak < 3:
                continue

            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-streak]['ratio_400_above'] or 0)
            if r400_chg < 3.0:
                continue

            r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-streak]['ratio_1000_above'] or 0)
            sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0

            holders_chg = ((float(rows[i]['total_holders'] or 0) - float(rows[i-streak]['total_holders'] or 0)) /
                          max(float(rows[i-streak]['total_holders'] or 1), 1) * 100)

            if sync >= 0.5 and holders_chg <= -2.0:
                cursor.execute("""
                    SELECT close_price FROM daily_prices
                    WHERE stock_code = %s AND date = %s
                """, (stock_code, rows[i]['date']))

                price_row = cursor.fetchone()
                if price_row and float(price_row['close_price'] or 0) >= 300:
                    signals.append({
                        'code': stock_code,
                        'engine': 'main',
                        'signal_date': rows[i]['date'],
                    })

    return signals

def scan_backup_engine(date_range=None):
    """掃描備位引擎訊號"""
    signals = []
    date_filter = ""
    if date_range == '2023':
        date_filter = "AND date >= '20230101' AND date <= '20231231'"

    for stock_code in all_stocks:
        cursor.execute(f"""
            SELECT date, ratio_400_above, total_holders
            FROM holdings WHERE stock_code = %s {date_filter}
            ORDER BY date
        """, (stock_code,))

        rows = list(cursor.fetchall())
        if len(rows) < 4:
            continue

        for i in range(3, len(rows)):
            h_now = float(rows[i]['total_holders'] or 0)
            h_3w_ago = float(rows[i-3]['total_holders'] or 0)

            if h_3w_ago <= 0:
                continue

            holder_flee = (h_now - h_3w_ago) / h_3w_ago * 100
            if holder_flee > -15.0:
                continue

            r400_now = float(rows[i]['ratio_400_above'] or 0)
            r400_3w_ago = float(rows[i-3]['ratio_400_above'] or 0)
            r400_chg = r400_now - r400_3w_ago

            if r400_chg < 2.0:
                continue

            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (stock_code, rows[i]['date']))

            price_row = cursor.fetchone()
            if price_row and float(price_row['close_price'] or 0) >= 50:
                signals.append({
                    'code': stock_code,
                    'engine': 'backup',
                    'signal_date': rows[i]['date'],
                })

    return signals

# ================================================================================
# 修正版回測函數 - 正確的日曆天數
# ================================================================================

def run_corrected_backtest(main_sigs, backup_sigs, max_positions, max_hold_calendar_days,
                          period_start_date, period_end_date, period_name):
    """
    正確的日曆天數回測

    關鍵邏輯：
    1. 遍歷每個日曆日（包括週末和假日）
    2. 對於每個持倉，計算已持倒的日曆天數
    3. 如果日曆天數 >= max_hold_calendar_days，標記為應該出場
    4. 有可用價格時執行出場
    """

    conn_local = get_db_connection()
    cursor_local = conn_local.cursor(cursor_factory=RealDictCursor)

    main_months = {s['signal_date'][:7] for s in main_sigs}
    backup_filtered = [s for s in backup_sigs if s['signal_date'][:7] not in main_months]

    all_signals = sorted(main_sigs + backup_filtered, key=lambda s: s['signal_date'])

    pending_orders = {}
    for sig in all_signals:
        if sig['code'] not in pending_orders:
            sig_date = sig['signal_date']
            # 5個交易日後進場
            sig_date_obj = datetime.strptime(sig_date, '%Y%m%d')
            entry_date_obj = sig_date_obj + timedelta(days=5)
            entry_date = entry_date_obj.strftime('%Y%m%d')

            cursor_local.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (sig['code'], entry_date))

            price_row = cursor_local.fetchone()
            if price_row:
                pending_orders[sig['code']] = {
                    'signal_date': sig['signal_date'],
                    'entry_date': entry_date,
                    'entry_price': float(price_row['close_price']),
                    'engine': sig['engine']
                }

    positions = {}
    trades = []
    cash = CAPITAL

    # 使用日曆日循環 - 每天都檢查
    start_date_obj = datetime.strptime(period_start_date, '%Y%m%d')
    end_date_obj = datetime.strptime(period_end_date, '%Y%m%d')
    current_date_obj = start_date_obj

    while current_date_obj <= end_date_obj:
        current_date = current_date_obj.strftime('%Y%m%d')

        # ========== 出場檢查 (日曆天數) ==========
        exited_codes = []
        for code, pos in list(positions.items()):
            entry_date_obj = datetime.strptime(pos['entry_date'], '%Y%m%d')
            calendar_days = (current_date_obj - entry_date_obj).days

            # 先檢查停損和到期條件
            should_exit = False
            reason = ''

            # 1. 檢查停損（需要有價格）
            cursor_local.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (code, current_date))

            price_row = cursor_local.fetchone()
            if price_row:
                current_price = float(price_row['close_price'])
                ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100

                if ret <= STOP_LOSS_PCT:
                    should_exit = True
                    reason = '停損'
            else:
                current_price = None

            # 2. 檢查到期（無條件檢查）
            if not should_exit and calendar_days >= max_hold_calendar_days:
                should_exit = True
                reason = '到期'
                # 使用最後一次有效的價格，或尋找最近的歷史價格
                if current_price is None:
                    # 往前找到最近的有效價格
                    cursor_local.execute("""
                        SELECT close_price FROM daily_prices
                        WHERE stock_code = %s AND date <= %s
                        ORDER BY date DESC LIMIT 1
                    """, (code, current_date))
                    hist_row = cursor_local.fetchone()
                    if hist_row:
                        current_price = float(hist_row['close_price'])
                    else:
                        # 無法找到任何價格，跳過此位置
                        current_date_obj += timedelta(days=1)
                        continue

            # 執行出場
            if should_exit and current_price is not None:
                sell_cost = SELL_FEE + SELL_TAX
                ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                net_ret = ret - sell_cost * 100
                pnl = pos['invested'] * net_ret / 100

                cash += pos['invested'] + pnl
                trades.append({
                    '股票': code,
                    '引擎': pos['engine'],
                    '進場日期': pos['entry_date'],
                    '進場價格': f"{pos['entry_price']:.2f}",
                    '出場日期': current_date,
                    '出場價格': f"{current_price:.2f}",
                    '日曆天數': calendar_days,
                    '收益率%': f"{net_ret:+.2f}%",
                    '收益金額': f"NT${pnl:+,.0f}",
                    '出場原因': reason,
                    '投入資金': f"NT${pos['invested']:,.0f}"
                })
                exited_codes.append(code)

        for code in exited_codes:
            del positions[code]

        # ========== 進場檢查 ==========
        for code, order in list(pending_orders.items()):
            if len(positions) >= max_positions or code in positions:
                continue

            if order['entry_date'] == current_date:
                per_position = CAPITAL // max_positions
                shares = int(per_position / (order['entry_price'] * (1 + BUY_FEE)))

                if shares <= 0:
                    continue

                invested = shares * order['entry_price'] * (1 + BUY_FEE)

                if invested > cash:
                    continue

                cash -= invested
                positions[code] = {
                    'entry_price': order['entry_price'],
                    'entry_date': order['entry_date'],
                    'invested': invested,
                    'engine': order['engine']
                }
                del pending_orders[code]

        # 推進到下一個日期
        current_date_obj += timedelta(days=1)

    conn_local.close()
    return pd.DataFrame(trades)

# ================================================================================
# 執行回測
# ================================================================================

print("\n" + "="*80)
print("掃描訊號...")
print("="*80)

# 全週期
main_full = scan_main_engine()
backup_full = scan_backup_engine()
print(f"\n【全週期】主引擎：{len(main_full)}，備位引擎：{len(backup_full)}")

# 2023 年
main_2023 = scan_main_engine('2023')
backup_2023 = scan_backup_engine('2023')
print(f"【2023年】主引擎：{len(main_2023)}，備位引擎：{len(backup_2023)}")

# 回測配置：日曆天數（不是交易日）
configs = [
    (42, 3, "6週+3個持倉"),    # 42 個日曆日
    (42, 6, "6週+6個持倉"),
    (90, 3, "90天+3個持倉"),   # 90 個日曆日
    (90, 6, "90天+6個持倉"),
]

print("\n" + "="*80)
print("執行回測（日曆天數）...")
print("="*80)

# 全週期回測
print("\n【全週期 2022-2025】")
for hold_days, positions_max, label in configs:
    trades_df = run_corrected_backtest(main_full, backup_full, positions_max, hold_days,
                                      '20220101', '20251231', 'full')

    output_file = f'/tmp/trading_reports/修正版_{label}_全週期.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    if len(trades_df) > 0:
        total_pnl = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float).sum()
        max_days = trades_df['日曆天數'].max()
        print(f"  ✓ {label}: {len(trades_df):3d} 筆交易 → 獲利 NT${total_pnl:+10,.0f} | 最大持倒 {max_days} 日")
    else:
        print(f"  ⚠️  {label}: 無交易")

# 2023 年回測
print("\n【2023年空頭】")
for hold_days, positions_max, label in configs:
    trades_df = run_corrected_backtest(main_2023, backup_2023, positions_max, hold_days,
                                      '20230101', '20231231', '2023')

    output_file = f'/tmp/trading_reports/修正版_{label}_2023年.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    if len(trades_df) > 0:
        total_pnl = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float).sum()
        max_days = trades_df['日曆天數'].max()
        print(f"  ✓ {label}: {len(trades_df):3d} 筆交易 → 獲利 NT${total_pnl:+10,.0f} | 最大持倒 {max_days} 日")
    else:
        print(f"  ⚠️  {label}: 無交易")

print("\n✅ 回測完成")
print("位置：/tmp/trading_reports/修正版_*.csv")

conn.close()
