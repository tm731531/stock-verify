#!/usr/bin/env python3
"""
真實回測對比：v7 基準 vs v7+v4 備位引擎
===============================================

目的：驗證「備位引擎從4週任意下降改為4週逐步下降」的真實效果

配置：
v7 基準 (backup_v3):
  - 備位引擎：4週散戶↓≥5.0% (任意下降)
  - 進場：信號日+3~7天，close_price≤limit_price時進場
  - 結果基準：+NT$383,291 (90天+3個持倉)

v7+v4 (backup_v4):  
  - 備位引擎：4週逐步下降（每週都在減）
  - 進場邏輯同上
  - 結果預期：改善?

"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
from collections import defaultdict

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

print("="*80)
print("v7 真實回測對比：基準 vs 逐步下降備位引擎")
print("="*80)

# 全局配置
CAPITAL = 500_000
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
STOP_LOSS_PCT = -7.0
TAKE_PROFIT_PCT = 15.0
TAKE_PROFIT_PULLBACK = 10.0
LIMIT_MULT = 1.03

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

print("\n加載數據...")

# 日期
cursor.execute("SELECT DISTINCT date FROM daily_prices WHERE date >= '20220101' AND date <= '20251231' ORDER BY date")
all_dates = [r['date'] for r in cursor.fetchall()]
date_to_idx = {d: i for i, d in enumerate(all_dates)}

# 價格
cursor.execute("SELECT stock_code, date, open_price, high_price, low_price, close_price FROM daily_prices WHERE date >= '20220101' AND date <= '20251231'")
prices = defaultdict(dict)
ohlcv = defaultdict(lambda: defaultdict(dict))
for r in cursor.fetchall():
    code, date = r['stock_code'], r['date']
    close_price = float(r['close_price']) if r['close_price'] else None
    prices[code][date] = close_price
    ohlcv[code][date] = {
        'open': float(r['open_price']) if r['open_price'] else None,
        'high': float(r['high_price']) if r['high_price'] else None,
        'low': float(r['low_price']) if r['low_price'] else None,
        'close': close_price,
    }

# 持倉
cursor.execute("SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders FROM holdings WHERE stock_code NOT LIKE '00%' ORDER BY stock_code, date")
holdings = defaultdict(list)
for r in cursor.fetchall():
    holdings[r['stock_code']].append(r)

print(f"✓ {len(all_dates)} 個交易日")
print(f"✓ {len(prices)} 支股票有價格")
print(f"✓ {len(holdings)} 支股票有持倉")

# ================================================================================
# 掃描主引擎訊號（不變）
# ================================================================================

def iso_week_key(date_str):
    d = datetime.strptime(date_str, '%Y%m%d').date()
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'

def dedupe_by_week(grp):
    seen = {}
    for row in grp:
        wk = iso_week_key(row['date'])
        seen[wk] = row
    return list(seen.values())

print("\n掃描主引擎訊號...")
main_signals = []
for code in holdings:
    grp = dedupe_by_week(holdings[code])
    if len(grp) < 4:
        continue
    
    for i in range(3, len(grp)):
        streak = 0
        for j in range(i, 0, -1):
            if float(grp[j]['ratio_400_above'] or 0) > float(grp[j-1]['ratio_400_above'] or 0):
                streak += 1
            else:
                break
        
        if streak < 3:
            continue
        
        si = i - streak
        r400_chg = float(grp[i]['ratio_400_above'] or 0) - float(grp[si]['ratio_400_above'] or 0)
        r1000_chg = float(grp[i]['ratio_1000_above'] or 0) - float(grp[si]['ratio_1000_above'] or 0)
        sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
        h_chg = (float(grp[i]['total_holders']) - float(grp[si]['total_holders'])) / float(grp[si]['total_holders']) * 100 if float(grp[si]['total_holders']) > 0 else 0
        
        if r400_chg < 3.0 or sync < 0.5 or h_chg > -2.0:
            continue
        
        sig_date = grp[i]['date']
        price = prices[code].get(sig_date, 0)
        if price < 300:
            continue
        
        limit_price = round(price * LIMIT_MULT, 1)
        main_signals.append({
            'code': code,
            'signal_date': sig_date,
            'engine': 'main',
            'limit_price': limit_price,
        })

print(f"✓ 主引擎: {len(main_signals)} 個訊號")

# ================================================================================
# 掃描備位引擎 v3（4週任意下降）
# ================================================================================

def scan_backup_v3():
    """4週任意下降"""
    signals = []
    for code in holdings:
        grp = dedupe_by_week(holdings[code])
        if len(grp) < 5:
            continue
        
        for i in range(4, len(grp)):
            h_now = float(grp[i]['total_holders'])
            h_bef = float(grp[i-4]['total_holders'])
            
            if h_bef <= 0:
                continue
            
            flee = (h_now - h_bef) / h_bef * 100
            if flee > -5.0:
                continue
            
            sig_date = grp[i]['date']
            price = prices[code].get(sig_date, 0)
            if price < 50:
                continue
            
            # MA20
            price_list = [prices[code].get(d, None) for d in all_dates if d <= sig_date]
            if len(price_list) < 20:
                continue
            ma20 = sum([p for p in price_list[-20:] if p]) / 20 if len([p for p in price_list[-20:] if p]) >= 20 else 0
            if price <= ma20:
                continue
            
            limit_price = round(price * LIMIT_MULT, 1)
            signals.append({
                'code': code,
                'signal_date': sig_date,
                'engine': 'backup_v3',
                'limit_price': limit_price,
            })
    
    return signals

# ================================================================================
# 掃描備位引擎 v4（4週逐步下降）
# ================================================================================

def scan_backup_v4():
    """4週逐步下降（每週都在減）"""
    signals = []
    for code in holdings:
        grp = dedupe_by_week(holdings[code])
        if len(grp) < 5:
            continue
        
        for i in range(4, len(grp)):
            # 檢查4週是否持續下降
            h_vals = [float(grp[i-4]['total_holders']), 
                      float(grp[i-3]['total_holders']),
                      float(grp[i-2]['total_holders']),
                      float(grp[i-1]['total_holders']),
                      float(grp[i]['total_holders'])]
            
            is_continuous = all(h_vals[j] > h_vals[j+1] for j in range(4))
            if not is_continuous:
                continue
            
            h_now = h_vals[4]
            h_bef = h_vals[0]
            
            if h_bef <= 0:
                continue
            
            flee = (h_now - h_bef) / h_bef * 100
            if flee > -5.0:
                continue
            
            sig_date = grp[i]['date']
            price = prices[code].get(sig_date, 0)
            if price < 50:
                continue
            
            # MA20
            price_list = [prices[code].get(d, None) for d in all_dates if d <= sig_date]
            if len(price_list) < 20:
                continue
            ma20 = sum([p for p in price_list[-20:] if p]) / 20 if len([p for p in price_list[-20:] if p]) >= 20 else 0
            if price <= ma20:
                continue
            
            limit_price = round(price * LIMIT_MULT, 1)
            signals.append({
                'code': code,
                'signal_date': sig_date,
                'engine': 'backup_v4',
                'limit_price': limit_price,
            })
    
    return signals

print("掃描備位引擎 v3...")
backup_v3_signals = scan_backup_v3()
print(f"✓ 備位 v3: {len(backup_v3_signals)} 個訊號")

print("掃描備位引擎 v4...")
backup_v4_signals = scan_backup_v4()
print(f"✓ 備位 v4: {len(backup_v4_signals)} 個訊號")

# ================================================================================
# 回測函數（v7 原始邏輯）
# ================================================================================

def run_backtest(main_sigs, backup_sigs, max_positions, max_hold_days, label):
    """執行回測（v7 原始進場邏輯）"""
    
    # 主備位去重：按月份
    main_months = {s['signal_date'][:7] for s in main_sigs}
    backup_filtered = [s for s in backup_sigs if s['signal_date'][:7] not in main_months]
    
    all_signals = sorted(main_sigs + backup_filtered, key=lambda s: s['signal_date'])
    
    # 建立進場隊列
    pending_entry = {}
    for sig in all_signals:
        if sig['code'] not in pending_entry:
            sig_date = sig['signal_date']
            sig_idx = date_to_idx.get(sig_date, -1)
            
            # 信號日+3~7天，找到符合 limit_price 的第一個日子
            found_entry_date = None
            for offset in range(3, 8):
                entry_idx = sig_idx + offset
                if entry_idx >= len(all_dates):
                    break
                entry_date = all_dates[entry_idx]
                entry_price = prices[sig['code']].get(entry_date, None)
                
                if entry_price and entry_price <= sig['limit_price']:
                    found_entry_date = entry_date
                    found_entry_price = entry_price
                    break
            
            if found_entry_date:
                pending_entry[sig['code']] = {
                    'signal_date': sig_date,
                    'entry_date': found_entry_date,
                    'entry_price': found_entry_price,
                    'engine': sig['engine'],
                }
    
    # 模擬交易
    positions = {}
    trades = []
    cash = CAPITAL
    
    start_date_obj = datetime.strptime(all_dates[0], '%Y%m%d')
    end_date_obj = datetime.strptime(all_dates[-1], '%Y%m%d')
    current_date_obj = start_date_obj
    
    while current_date_obj <= end_date_obj:
        current_date = current_date_obj.strftime('%Y%m%d')
        
        # 出場檢查
        for code in list(positions.keys()):
            pos = positions[code]
            entry_date_obj = datetime.strptime(pos['entry_date'], '%Y%m%d')
            cal_days = (current_date_obj - entry_date_obj).days
            
            current_price = prices[code].get(current_date)
            
            should_exit = False
            reason = ''
            
            if current_price:
                ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                
                if ret <= STOP_LOSS_PCT:
                    should_exit = True
                    reason = '停損'
                elif not pos.get('tp_activated') and ret >= TAKE_PROFIT_PCT:
                    pos['tp_activated'] = True
                    pos['tp_highest'] = ret
                elif pos.get('tp_activated'):
                    pos['tp_highest'] = max(pos['tp_highest'], ret)
                    if pos['tp_highest'] - ret >= TAKE_PROFIT_PULLBACK:
                        should_exit = True
                        reason = '停利'
            
            if not should_exit and cal_days >= max_hold_days:
                should_exit = True
                reason = '到期'
                if not current_price:
                    for k in range(date_to_idx.get(current_date, -1), -1, -1):
                        p = prices[code].get(all_dates[k])
                        if p:
                            current_price = p
                            break
            
            if should_exit and current_price:
                sell_cost = (SELL_FEE + SELL_TAX) * 100
                ret = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                net_ret = ret - sell_cost
                pnl = pos['invested'] * net_ret / 100
                
                cash += pos['invested'] + pnl
                trades.append({
                    'code': code,
                    'engine': pos['engine'],
                    'entry_date': pos['entry_date'],
                    'entry_price': pos['entry_price'],
                    'exit_date': current_date,
                    'exit_price': current_price,
                    'days': cal_days,
                    'ret': ret,
                    'pnl': pnl,
                    'reason': reason,
                })
                del positions[code]
        
        # 進場檢查
        for code in list(pending_entry.keys()):
            if code not in positions and len(positions) < max_positions:
                sig = pending_entry[code]
                if sig['entry_date'] == current_date:
                    invested = cash / max_positions
                    positions[code] = {
                        'signal_date': sig['signal_date'],
                        'entry_date': sig['entry_date'],
                        'entry_price': sig['entry_price'],
                        'engine': sig['engine'],
                        'invested': invested,
                        'tp_activated': False,
                        'tp_highest': 0,
                    }
                    cash -= invested
                    del pending_entry[code]
        
        current_date_obj += timedelta(days=1)
    
    # 統計
    if trades:
        win_trades = [t for t in trades if t['pnl'] > 0]
        total_pnl = sum([t['pnl'] for t in trades])
        win_rate = len(win_trades) / len(trades) * 100
        
        return {
            'label': label,
            'trades': len(trades),
            'pnl': total_pnl,
            'win_rate': win_rate,
            'trades_detail': trades,
        }
    else:
        return {
            'label': label,
            'trades': 0,
            'pnl': 0,
            'win_rate': 0,
            'trades_detail': [],
        }

# ================================================================================
# 執行回測
# ================================================================================

print("\n" + "="*80)
print("執行回測")
print("="*80)

configs = [
    (42, 3, "6週+3個持倉"),
    (42, 6, "6週+6個持倉"),
    (90, 3, "90天+3個持倉"),
    (90, 6, "90天+6個持倉"),
]

results = []

for max_hold, max_pos, label in configs:
    print(f"\n【{label}】")
    
    result_v3 = run_backtest(main_signals, backup_v3_signals, max_pos, max_hold, f"{label} (v3)")
    result_v4 = run_backtest(main_signals, backup_v4_signals, max_pos, max_hold, f"{label} (v4)")
    
    print(f"  v3: {result_v3['trades']} 筆 | {result_v3['pnl']:+.0f} | {result_v3['win_rate']:.1f}%")
    print(f"  v4: {result_v4['trades']} 筆 | {result_v4['pnl']:+.0f} | {result_v4['win_rate']:.1f}%")
    
    diff = result_v4['pnl'] - result_v3['pnl']
    print(f"  改善: {diff:+.0f} {'✅' if diff > 0 else '❌'}")
    
    results.append((label, result_v3, result_v4, diff))

# ================================================================================
# 摘要
# ================================================================================

print("\n" + "="*80)
print("摘要")
print("="*80)

print(f"\n{'配置':<15} {'v3獲利':<15} {'v4獲利':<15} {'改善':<15}")
print("-" * 60)

total_v3 = 0
total_v4 = 0

for label, r_v3, r_v4, diff in results:
    print(f"{label:<15} {r_v3['pnl']:>+14.0f} {r_v4['pnl']:>+14.0f} {diff:>+14.0f}")
    total_v3 += r_v3['pnl']
    total_v4 += r_v4['pnl']

print("-" * 60)
print(f"{'合計':<15} {total_v3:>+14.0f} {total_v4:>+14.0f} {total_v4-total_v3:>+14.0f}")

print("\n" + "="*80)

conn.close()
