"""
V7 策略回測：特殊事件排除 - 永久 vs 1年過期對比
=================================================

比較兩種排除邏輯的績效：
  A. 永久排除：歷史上曾有單週 >5% 變動的股票永遠排除
  B. 1年排除：特殊事件排除標記 1 年後自動解除
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

# ── 資料載入 ──

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# 取得所有日期和股票
cursor.execute("SELECT DISTINCT date FROM daily_prices ORDER BY date")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_index = {d: i for i, d in enumerate(all_dates)}

cursor.execute("SELECT DISTINCT stock_code FROM holdings WHERE stock_code NOT LIKE '00%%' ORDER BY stock_code")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]

# 載入所有 TDCC 歷史資料
print("[載入] TDCC 歷史資料...")
cursor.execute("""
    SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
    FROM holdings ORDER BY stock_code, date
""")
tdcc_data = defaultdict(list)
for row in cursor.fetchall():
    tdcc_data[row['stock_code']].append({
        'date': row['date'],
        'r400': float(row['ratio_400_above'] or 0),
        'r1000': float(row['ratio_1000_above'] or 0),
        'holders': float(row['total_holders'] or 0),
    })

# 載入日線價格
print("[載入] 日線價格...")
cursor.execute("SELECT stock_code, date, close_price FROM daily_prices ORDER BY stock_code, date")
price_data = defaultdict(dict)
for row in cursor.fetchall():
    price_data[row['stock_code']][row['date']] = float(row['close_price'])

conn.close()

print(f"✓ 日期: {len(all_dates)} 個 ({all_dates[0]} ~ {all_dates[-1]})")
print(f"✓ 股票: {len(all_stocks)} 支")

# ── 特殊事件標記邏輯 ──

def build_special_flags_permanent(tdcc_data):
    """永久排除：歷史上曾有單週 >5% 變動的股票永遠排除"""
    special = set()
    for code, grp in tdcc_data.items():
        for i in range(1, len(grp)):
            if abs(grp[i]['r400'] - grp[i-1]['r400']) > 5.0:
                special.add(code)
                break
    return special

def build_special_flags_expiry(tdcc_data, event_date, expiry_days=365):
    """1年排除：特殊事件排除標記 1 年後自動解除"""
    special = {}  # {code: event_date}
    for code, grp in tdcc_data.items():
        for i in range(1, len(grp)):
            if abs(grp[i]['r400'] - grp[i-1]['r400']) > 5.0:
                event_tdcc_date = grp[i]['date']
                # 如果特殊事件在 event_date 前 1 年內發生，就排除
                event_dt = datetime.strptime(event_tdcc_date, '%Y%m%d')
                scan_dt = datetime.strptime(event_date, '%Y%m%d')
                days_diff = (scan_dt - event_dt).days
                if 0 <= days_diff <= expiry_days:
                    special[code] = event_tdcc_date
                break
    return special

# ── 訊號掃描 ──

def scan_signals_with_special_flags(tdcc_data, price_data, all_dates, special_codes, mode='permanent'):
    """
    掃描訊號（主引擎）
    條件：連升≥3週 + 大戶↑≥3% + 同步≥50% + 散戶↓≥2% + 股價≥300
    """
    signals = []

    for code in all_stocks:
        if code in special_codes:
            continue

        grp = tdcc_data[code]
        if len(grp) < 4:
            continue

        for i in range(3, len(grp)):
            r400 = grp[i]['r400']
            r400_prev3 = grp[i-3]['r400']
            r400_prev2 = grp[i-2]['r400']
            r400_prev1 = grp[i-1]['r400']

            # 連升 3 週
            if not (r400_prev3 < r400_prev2 < r400_prev1 < r400):
                continue

            # 大戶變化 ≥3%
            r400_chg = r400 - r400_prev3
            if r400_chg < 3.0:
                continue

            # 同步性 ≥50%
            r1000_chg = grp[i]['r1000'] - grp[i-3]['r1000']
            sync = r1000_chg / max(r400_chg, 0.001)
            if sync < 0.5:
                continue

            # 散戶變化 ≤-2%
            holders_now = grp[i]['holders']
            holders_prev3 = grp[i-3]['holders']
            holder_chg = (holders_now - holders_prev3) / max(holders_prev3, 1) * 100
            if holder_chg > -2.0:
                continue

            # 股價 ≥300
            signal_date = grp[i]['date']
            if signal_date not in price_data[code]:
                continue
            price = price_data[code][signal_date]
            if price < 300:
                continue

            signals.append({
                'code': code,
                'signal_date': signal_date,
                'r400_chg': round(r400_chg, 2),
                'sync': round(sync * 100, 1),
                'holder_chg': round(holder_chg, 1),
                'price': price,
                'limit_price': round(price * 1.03, 1),
            })

    return sorted(signals, key=lambda x: x['signal_date'])

# ── 回測模擬 ──

def backtest(signals, price_data, all_dates, label):
    """投組模擬"""
    print(f"\n{'='*80}")
    print(f"回測：{label}")
    print(f"{'='*80}\n")

    CAPITAL = 500_000
    MAX_POSITIONS = 4
    PER_POSITION = 125_000
    STOP_LOSS_PCT = -7.0
    TRAILING_ACTIVATE_PCT = 15.0
    TRAILING_STOP_PCT = 10.0
    BUY_FEE = 0.001425
    SELL_FEE = 0.001425
    SELL_TAX = 0.003
    SELL_COST = SELL_FEE + SELL_TAX
    MAX_HOLD_DAYS = 90

    cash = CAPITAL
    positions = {}  # {code: {buy_date, buy_price, shares, cost_basis, peak_price}}
    trades = []
    date_idx = 0

    for current_date in all_dates:
        # ── 1. 檢查出場 ──
        closed_codes = []
        for code, pos in positions.items():
            if code not in price_data or current_date not in price_data[code]:
                continue

            cp = price_data[code][current_date]
            days_held = (datetime.strptime(current_date, '%Y%m%d') -
                        datetime.strptime(pos['buy_date'], '%Y%m%d')).days

            # 更新最高價
            pos['peak_price'] = max(pos['peak_price'], cp)
            pos['days_held'] = days_held

            ret_pct = (cp - pos['buy_price']) / pos['buy_price'] * 100
            peak_gain_pct = (pos['peak_price'] - pos['buy_price']) / pos['buy_price'] * 100
            drawdown_pct = (cp - pos['peak_price']) / pos['peak_price'] * 100

            # 出場條件
            exit_reason = None
            if ret_pct <= STOP_LOSS_PCT:
                exit_reason = '停損'
            elif peak_gain_pct >= TRAILING_ACTIVATE_PCT and drawdown_pct <= -TRAILING_STOP_PCT:
                exit_reason = '停利'
            elif days_held >= MAX_HOLD_DAYS:
                exit_reason = '到期'

            if exit_reason:
                sell_value = pos['shares'] * cp
                sell_cost = sell_value * SELL_COST
                net_proceeds = sell_value - sell_cost
                profit = net_proceeds - pos['cost_basis']
                cash += net_proceeds

                trades.append({
                    'code': code,
                    'buy_date': pos['buy_date'],
                    'sell_date': current_date,
                    'buy_price': pos['buy_price'],
                    'sell_price': cp,
                    'shares': pos['shares'],
                    'profit': profit,
                    'return_pct': ret_pct,
                    'days_held': days_held,
                    'exit_reason': exit_reason,
                })
                closed_codes.append(code)

        for code in closed_codes:
            del positions[code]

        # ── 2. 檢查進場 ──
        day_signals = [s for s in signals if s['signal_date'] == current_date]
        for sig in day_signals:
            if sig['code'] in positions:
                continue
            if len(positions) >= MAX_POSITIONS:
                continue
            if cash < PER_POSITION:
                continue

            shares = int(PER_POSITION / sig['price'])
            cost_basis = shares * sig['price'] * (1 + BUY_FEE)
            if cost_basis > cash:
                continue

            cash -= cost_basis
            positions[sig['code']] = {
                'buy_date': current_date,
                'buy_price': sig['price'],
                'shares': shares,
                'cost_basis': cost_basis,
                'peak_price': sig['price'],
                'days_held': 0,
            }

        # ── 3. 計算淨值 ──
        portfolio_value = cash
        for code, pos in positions.items():
            if code in price_data and current_date in price_data[code]:
                portfolio_value += pos['shares'] * price_data[code][current_date]

    # ── 結算未平倉 ──
    last_date = all_dates[-1]
    for code, pos in positions.items():
        if code in price_data and last_date in price_data[code]:
            cp = price_data[code][last_date]
            ret_pct = (cp - pos['buy_price']) / pos['buy_price'] * 100
            profit = pos['shares'] * cp - pos['cost_basis']
            trades.append({
                'code': code,
                'buy_date': pos['buy_date'],
                'sell_date': 'OPEN',
                'buy_price': pos['buy_price'],
                'sell_price': cp,
                'shares': pos['shares'],
                'profit': profit,
                'return_pct': ret_pct,
                'days_held': pos['days_held'],
                'exit_reason': '未平倉',
            })

    # ── 績效統計 ──
    closed = [t for t in trades if t['exit_reason'] != '未平倉']
    wins = [t for t in closed if t['profit'] > 0]
    losses = [t for t in closed if t['profit'] <= 0]

    print(f"訊號數: {len(signals)} 個")
    print(f"交易數: {len(trades)} 筆 (已平倉: {len(closed)}, 未平倉: {len(trades)-len(closed)})")

    if closed:
        wr = len(wins) / len(closed) * 100
        avg_win = np.mean([t['return_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['return_pct'] for t in losses]) if losses else 0
        total_profit = sum(t['profit'] for t in wins)
        total_loss = sum(t['profit'] for t in losses)

        print(f"勝率: {len(wins)}/{len(closed)} ({wr:.1f}%)")
        print(f"平均報酬: 贏 {avg_win:+.2f}% / 虧 {avg_loss:+.2f}%")
        print(f"總損益: 獲利 {total_profit:+,.0f} / 虧損 {total_loss:+,.0f} = 淨 {total_profit+total_loss:+,.0f}")

    # 最終淨值
    final_value = CAPITAL
    for t in trades:
        if t['exit_reason'] != '未平倉':
            final_value += t['profit']
        else:
            final_value += t['profit']

    total_return = (final_value - CAPITAL) / CAPITAL * 100
    print(f"\n初始資金: {CAPITAL:,.0f}")
    print(f"最終淨值: {final_value:,.0f}")
    print(f"總報酬: {total_return:+.2f}%")

    return {
        'signals': len(signals),
        'trades': len(trades),
        'closed_trades': len(closed),
        'win_rate': len(wins) / len(closed) * 100 if closed else 0,
        'total_profit': sum(t['profit'] for t in wins) if wins else 0,
        'total_loss': sum(t['profit'] for t in losses) if losses else 0,
        'final_value': final_value,
        'total_return_pct': total_return,
    }

# ── 執行對比回測 ──

print("\n" + "="*80)
print("掃描訊號")
print("="*80)

# 版本 A：永久排除
print("\n[A] 永久排除 - 掃描中...")
special_permanent = build_special_flags_permanent(tdcc_data)
signals_a = scan_signals_with_special_flags(tdcc_data, price_data, all_dates, special_permanent, 'permanent')
print(f"    排除股票: {len(special_permanent)} 檔")
print(f"    訊號數: {len(signals_a)} 個")

# 版本 B：1年排除（用最新日期）
print("\n[B] 1年排除 - 掃描中...")
latest_date = all_dates[-1]
special_expiry = build_special_flags_expiry(tdcc_data, latest_date, expiry_days=365)
signals_b = scan_signals_with_special_flags(tdcc_data, price_data, all_dates, special_expiry, 'expiry')
print(f"    1年內排除股票: {len(special_expiry)} 檔")
print(f"    訊號數: {len(signals_b)} 個")

# 回測
result_a = backtest(signals_a, price_data, all_dates, "A. 永久排除")
result_b = backtest(signals_b, price_data, all_dates, "B. 1年排除")

# ── 對比總結 ──

print("\n" + "="*80)
print("對比總結")
print("="*80)
print(f"\n{'':20} {'永久排除':>15} {'1年排除':>15} {'差異':>15}")
print(f"{'-'*65}")
print(f"{'訊號數':20} {result_a['signals']:>15.0f} {result_b['signals']:>15.0f} {result_b['signals']-result_a['signals']:>+15.0f}")
print(f"{'交易數':20} {result_a['trades']:>15.0f} {result_b['trades']:>15.0f} {result_b['trades']-result_a['trades']:>+15.0f}")
print(f"{'已平倉':20} {result_a['closed_trades']:>15.0f} {result_b['closed_trades']:>15.0f} {result_b['closed_trades']-result_a['closed_trades']:>+15.0f}")
print(f"{'勝率':20} {result_a['win_rate']:>14.1f}% {result_b['win_rate']:>14.1f}% {result_b['win_rate']-result_a['win_rate']:>+14.1f}%")
print(f"{'獲利':20} {result_a['total_profit']:>15,.0f} {result_b['total_profit']:>15,.0f} {result_b['total_profit']-result_a['total_profit']:>+15,.0f}")
print(f"{'虧損':20} {result_a['total_loss']:>15,.0f} {result_b['total_loss']:>15,.0f} {result_b['total_loss']-result_a['total_loss']:>+15,.0f}")
print(f"{'最終淨值':20} {result_a['final_value']:>15,.0f} {result_b['final_value']:>15,.0f} {result_b['final_value']-result_a['final_value']:>+15,.0f}")
print(f"{'總報酬':20} {result_a['total_return_pct']:>14.2f}% {result_b['total_return_pct']:>14.2f}% {result_b['total_return_pct']-result_a['total_return_pct']:>+14.2f}%")
print()
