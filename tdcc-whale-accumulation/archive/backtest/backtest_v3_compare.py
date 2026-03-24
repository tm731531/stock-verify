#!/usr/bin/env python3
"""
V3 備位引擎回測 - 4週任意下降邏輯（對比基準）
=============================================

v3 備位引擎信號條件：
1. 4週散戶減少 ≥ 5.0% (相對4週前，任意下降非持續)
2. 股價 > MA20
3. 股價 ≥ 50 元

此版本作為 v4 (4週持續下降) 的對比基準。
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

print("="*80)
print("v3 備位引擎回測 - 4週任意下降邏輯")
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

# 全週期數據
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
    ORDER BY date
""")
all_dates_full = sorted([row['date'] for row in cursor.fetchall()])

# 2023 年數據
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20230101' AND date <= '20231231'
    ORDER BY date
""")
all_dates_2023 = sorted([row['date'] for row in cursor.fetchall()])

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%'")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

print(f"✓ 全週期：{len(all_dates_full)} 個交易日")
print(f"✓ 2023年：{len(all_dates_2023)} 個交易日")
print(f"✓ {len(all_stocks)} 支股票")

# ================================================================================
# 掃描信號函數
# ================================================================================

def scan_main_engine(date_range=None):
    """掃描主引擎訊號（不變）"""
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

def scan_backup_engine_v3(date_range=None):
    """
    掃描備位引擎 v3 訊號 - 4週任意下降邏輯

    條件：
    1. 4週散戶減少 ≥ 5.0% (相對4週前，任意下降)
    2. 股價 > MA20
    3. 股價 ≥ 50 元
    """
    signals = []
    date_filter = ""
    if date_range == '2023':
        date_filter = "AND date >= '20230101' AND date <= '20231231'"

    for stock_code in all_stocks:
        cursor.execute(f"""
            SELECT date, total_holders
            FROM holdings WHERE stock_code = %s {date_filter}
            ORDER BY date
        """, (stock_code,))

        rows = list(cursor.fetchall())
        if len(rows) < 5:
            continue

        for i in range(4, len(rows)):
            # 1. 檢查4週散戶減少 ≥ 5.0% (任意下降，無需持續)
            h_i_minus_4 = float(rows[i-4]['total_holders'] or 0)
            h_i = float(rows[i]['total_holders'] or 0)

            if h_i_minus_4 <= 0:
                continue

            holder_decline_pct = (h_i - h_i_minus_4) / h_i_minus_4 * 100
            if holder_decline_pct > -5.0:
                continue  # 需要至少下降5%

            # 2. 檢查股價 > MA20 且股價 ≥ 50 元
            current_date = rows[i]['date']
            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (stock_code, current_date))

            price_row = cursor.fetchone()
            if not price_row:
                continue

            close_price = float(price_row['close_price'] or 0)
            if close_price < 50:
                continue

            # 計算 MA20
            cursor.execute("""
                SELECT AVG(close_price) as ma20 FROM (
                    SELECT close_price FROM daily_prices
                    WHERE stock_code = %s AND date <= %s
                    ORDER BY date DESC LIMIT 20
                ) t
            """, (stock_code, current_date))

            ma20_row = cursor.fetchone()
            ma20 = float(ma20_row['ma20'] or 0) if ma20_row and ma20_row['ma20'] else 0

            if close_price <= ma20:
                continue  # 股價需要 > MA20

            # 所有條件都滿足
            signals.append({
                'code': stock_code,
                'engine': 'backup_v3',
                'signal_date': current_date,
                'holder_decline': holder_decline_pct,
            })

    return signals

# ================================================================================
# 回測函數
# ================================================================================

def run_backtest(main_sigs, backup_sigs, max_positions, max_hold_calendar_days,
                 period_start_date, period_end_date):
    """執行回測"""

    conn_local = get_db_connection()
    cursor_local = conn_local.cursor(cursor_factory=RealDictCursor)

    main_months = {s['signal_date'][:7] for s in main_sigs}
    backup_filtered = [s for s in backup_sigs if s['signal_date'][:7] not in main_months]

    all_signals = sorted(main_sigs + backup_filtered, key=lambda s: s['signal_date'])

    pending_orders = {}
    for sig in all_signals:
        if sig['code'] not in pending_orders:
            sig_date = sig['signal_date']
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

    start_date_obj = datetime.strptime(period_start_date, '%Y%m%d')
    end_date_obj = datetime.strptime(period_end_date, '%Y%m%d')
    current_date_obj = start_date_obj

    while current_date_obj <= end_date_obj:
        current_date = current_date_obj.strftime('%Y%m%d')

        # ========== 出場檢查 ==========
        exited_codes = []
        for code, pos in list(positions.items()):
            entry_date_obj = datetime.strptime(pos['entry_date'], '%Y%m%d')
            calendar_days = (current_date_obj - entry_date_obj).days

            should_exit = False
            reason = ''

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

            if not should_exit and calendar_days >= max_hold_calendar_days:
                should_exit = True
                reason = '到期'
                if current_price is None:
                    cursor_local.execute("""
                        SELECT close_price FROM daily_prices
                        WHERE stock_code = %s AND date <= %s
                        ORDER BY date DESC LIMIT 1
                    """, (code, current_date))
                    hist_row = cursor_local.fetchone()
                    if hist_row:
                        current_price = float(hist_row['close_price'])
                    else:
                        current_date_obj += timedelta(days=1)
                        continue

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
print("\n【全週期 2022-2025】")
main_full = scan_main_engine()
backup_full_v3 = scan_backup_engine_v3()
print(f"  主引擎：{len(main_full):4d} 筆")
print(f"  備位 v3：{len(backup_full_v3):4d} 筆")

# 2023 年
print("\n【2023年空頭】")
main_2023 = scan_main_engine('2023')
backup_2023_v3 = scan_backup_engine_v3('2023')
print(f"  主引擎：{len(main_2023):4d} 筆")
print(f"  備位 v3：{len(backup_2023_v3):4d} 筆")

# 回測配置
configs = [
    (42, 3, "6週+3個持倉"),
    (42, 6, "6週+6個持倉"),
    (90, 3, "90天+3個持倉"),
    (90, 6, "90天+6個持倉"),
]

print("\n" + "="*80)
print("執行回測...")
print("="*80)

# 全週期回測
print("\n【全週期 2022-2025】")
results_full = []
for hold_days, positions_max, label in configs:
    trades_df = run_backtest(main_full, backup_full_v3, positions_max, hold_days,
                             '20220101', '20251231')

    output_file = f'/tmp/trading_reports/v3_{label}_全週期.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    if len(trades_df) > 0:
        total_pnl = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float).sum()
        win_count = len(trades_df[trades_df['收益金額'].str.extract(r'([+-])', expand=False) == '+'])
        win_rate = (win_count / len(trades_df) * 100) if len(trades_df) > 0 else 0

        results_full.append({
            'config': label,
            'trades': len(trades_df),
            'profit': total_pnl,
            'win_rate': win_rate,
        })

        print(f"  ✓ {label:15s}: {len(trades_df):3d} 筆 | 獲利 NT${total_pnl:+10,.0f} | 勝率 {win_rate:5.1f}%")
    else:
        print(f"  ⚠️  {label:15s}: 無交易")

# 2023 年回測
print("\n【2023年空頭】")
results_2023 = []
for hold_days, positions_max, label in configs:
    trades_df = run_backtest(main_2023, backup_2023_v3, positions_max, hold_days,
                             '20230101', '20231231')

    output_file = f'/tmp/trading_reports/v3_{label}_2023年.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    if len(trades_df) > 0:
        total_pnl = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float).sum()
        win_count = len(trades_df[trades_df['收益金額'].str.extract(r'([+-])', expand=False) == '+'])
        win_rate = (win_count / len(trades_df) * 100) if len(trades_df) > 0 else 0

        results_2023.append({
            'config': label,
            'trades': len(trades_df),
            'profit': total_pnl,
            'win_rate': win_rate,
        })

        print(f"  ✓ {label:15s}: {len(trades_df):3d} 筆 | 獲利 NT${total_pnl:+10,.0f} | 勝率 {win_rate:5.1f}%")
    else:
        print(f"  ⚠️  {label:15s}: 無交易")

print("\n✅ 回測完成")

conn.close()
