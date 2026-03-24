#!/usr/bin/env python3
"""
TDCC 鯨魚策略 v7 回測 - 用完整 OHLCV 資料

用開高收低進行日內邏輯：
- 進場：檢查 low_price ≤ limit_price
- 停損：檢查 low_price 觸及 -7%
- 停利：檢查 high_price 達 +15%，low_price 回落 10%
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict
from pathlib import Path

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

print("="*80)
print("TDCC 鯨魚策略 v7 回測 - 用完整 OHLCV 資料")
print("="*80)

CAPITAL = 500_000
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

print("\n加載數據...")

# 日期
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
    ORDER BY date
""")
all_dates = [r['date'] for r in cursor.fetchall()]
date_to_idx = {d: i for i, d in enumerate(all_dates)}

# 價格 - 加載完整 OHLCV
cursor.execute("""
    SELECT stock_code, date, open_price, high_price, low_price, close_price, volume
    FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
""")
prices = defaultdict(lambda: defaultdict(dict))
for r in cursor.fetchall():
    code = r['stock_code']
    date = r['date']
    prices[code][date] = {
        'open': r['open_price'],
        'high': r['high_price'],
        'low': r['low_price'],
        'close': float(r['close_price']) if r['close_price'] else None,
        'volume': r['volume']
    }

# TDCC 數據
cursor.execute("""
    SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    ORDER BY stock_code, date
""")
tdcc_data = defaultdict(list)
for r in cursor.fetchall():
    tdcc_data[r['stock_code']].append(r)

print(f"✓ {len(all_dates)} 個交易日")
print(f"✓ {len(prices)} 支股票有價格數據")
print(f"✓ {len(tdcc_data)} 支股票有 TDCC 數據")

# 統計 OHLCV 完整性
ohlcv_complete = 0
close_only = 0
for code in prices:
    for date in prices[code]:
        if prices[code][date].get('open') is not None:
            ohlcv_complete += 1
        else:
            close_only += 1

print(f"✓ 完整 OHLCV：{ohlcv_complete:,} 筆")
print(f"✓ 僅有收盤價：{close_only:,} 筆")

# ================================================================================
# 信號掃描 (簡化版)
# ================================================================================

def iso_week_key(date_str):
    d = datetime.strptime(date_str, '%Y%m%d')
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'

print("\n掃描信號...")

main_sigs = []
backup_sigs = []

for code in tdcc_data:
    hdgs = tdcc_data[code]
    if len(hdgs) < 3:
        continue

    for i in range(2, len(hdgs)):
        curr = hdgs[i]
        prev1 = hdgs[i-1]
        prev2 = hdgs[i-2]
        prev3 = hdgs[i-3] if i >= 3 else None

        # 主引擎
        if curr['ratio_400_above'] and prev1['ratio_400_above'] and prev2['ratio_400_above']:
            if (curr['ratio_400_above'] > prev1['ratio_400_above'] and
                prev1['ratio_400_above'] > prev2['ratio_400_above']):
                sig_price = prices[code].get(curr['date'], {}).get('close')
                if sig_price and sig_price >= 300:
                    main_sigs.append({
                        'type': 'main',
                        'code': code,
                        'sig_date': curr['date'],
                        'sig_price': sig_price
                    })

        # 備位引擎 (簡化)
        if prev3 and curr['total_holders']:
            pct_chg = (curr['total_holders'] - prev3['total_holders']) / prev3['total_holders'] * 100
            if pct_chg <= -15:
                sig_price = prices[code].get(curr['date'], {}).get('close')
                if sig_price and sig_price >= 50:
                    backup_sigs.append({
                        'type': 'backup',
                        'code': code,
                        'sig_date': curr['date'],
                        'sig_price': sig_price
                    })

print(f"✓ 主引擎：{len(main_sigs)} 個")
print(f"✓ 備位引擎：{len(backup_sigs)} 個")

# ================================================================================
# 回測引擎 (用 OHLCV)
# ================================================================================

def run_backtest(main_sigs, backup_sigs):
    positions = {}
    trades = []
    cash = CAPITAL

    start_date_obj = datetime.strptime(all_dates[0], '%Y%m%d')
    end_date_obj = datetime.strptime(all_dates[-1], '%Y%m%d')
    current_date_obj = start_date_obj

    # 簡單的進場隊列
    entry_queue = main_sigs[:20] + backup_sigs[:20]

    while current_date_obj <= end_date_obj:
        date = current_date_obj.strftime('%Y%m%d')

        # 出場檢查（用 OHLCV）
        codes_to_exit = []
        for code, pos in list(positions.items()):
            entry_date_obj = datetime.strptime(pos['entry_date'], '%Y%m%d')
            cal_days = (current_date_obj - entry_date_obj).days

            ohlcv = prices[code].get(date, {})

            should_exit = False
            reason = ''
            exit_price = float(ohlcv.get('close')) if ohlcv.get('close') else None  # 預設用收盤

            # 如果有開高收低，用日內邏輯
            if ohlcv.get('low') is not None and ohlcv.get('high') is not None:
                low_price = float(ohlcv['low'])
                high_price = float(ohlcv['high'])
                # 停損：檢查日內低價
                if low_price <= pos['entry_price'] * 0.93:
                    should_exit = True
                    reason = '停損'
                    exit_price = pos['entry_price'] * 0.93

                # 停利邏輯
                elif not pos['take_profit_activated']:
                    if high_price >= pos['entry_price'] * 1.15:
                        pos['take_profit_activated'] = True
                        pos['highest_price'] = high_price
                elif low_price <= pos['highest_price'] * 0.90:
                    should_exit = True
                    reason = '停利'
                    exit_price = pos['highest_price'] * 0.90

            # 時間到期
            if not should_exit and cal_days >= pos['max_hold_days']:
                should_exit = True
                reason = '到期'

            if should_exit and exit_price:
                pnl = (exit_price - pos['entry_price']) * pos['shares']
                pnl -= pos['shares'] * pos['entry_price'] * BUY_FEE
                pnl -= pos['shares'] * exit_price * SELL_FEE
                pnl -= pos['shares'] * exit_price * SELL_TAX

                trades.append({
                    'code': code,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'shares': pos['shares'],
                    'profit': pnl,
                    'return_pct': (exit_price - pos['entry_price']) / pos['entry_price'] * 100,
                    'reason': reason
                })
                cash += pos['shares'] * exit_price - pos['shares'] * exit_price * (SELL_FEE + SELL_TAX)
                codes_to_exit.append(code)

        for code in codes_to_exit:
            del positions[code]

        # 進場檢查
        for sig in entry_queue:
            if sig['sig_date'] <= date and sig['code'] not in positions:
                ohlcv = prices[sig['code']].get(date, {})
                if ohlcv.get('close'):
                    limit_price = float(sig['sig_price']) * 1.03
                    entry_price = float(ohlcv['close'])

                    # 如果有開高收低，檢查日內低價是否能進場
                    if ohlcv.get('low') is not None and ohlcv['low'] is not None:
                        low_price = float(ohlcv['low'])
                        if low_price <= limit_price:
                            entry_price = min(low_price, limit_price)

                    if cash > 125000:
                        shares = int(125000 / entry_price)
                        cost = shares * entry_price * (1 + BUY_FEE)
                        if cash >= cost:
                            positions[sig['code']] = {
                                'entry_date': date,
                                'entry_price': entry_price,
                                'shares': shares,
                                'max_hold_days': 90,
                                'take_profit_activated': False,
                                'highest_price': entry_price
                            }
                            cash -= cost

        current_date_obj += timedelta(days=1)

    return trades, cash

print("\n執行回測...")
trades, final_cash = run_backtest(main_sigs, backup_sigs)

total_return = (final_cash - CAPITAL) / CAPITAL * 100
print(f"\n✅ 回測完成！")
print(f"   交易筆數：{len(trades)}")
print(f"   最終資金：NT${final_cash:,.0f}")
print(f"   總報酬：{total_return:.1f}%")

if trades:
    wins = sum(1 for t in trades if t['profit'] > 0)
    print(f"   勝率：{wins/len(trades)*100:.1f}%")
    print(f"\n前 10 筆交易：")
    for i, t in enumerate(trades[:10], 1):
        print(f"   {i}. {t['code']} {t['entry_date']}-{t['exit_date']}: "
              f"{t['return_pct']:.1f}% ({t['reason']})")

conn.close()
