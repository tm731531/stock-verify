#!/usr/bin/env python3
"""
TDCC 鯨魚策略 v7 完整回測

完整實現：
1. 主引擎：連升3週+r400↑3%+同步≥50%+散戶↓≥2%+股價≥300
2. 備位引擎：4週散戶↓≥5%+站上MA20+股價≥50
3. 主備位去重：有主信號的周不用備位
4. 進場邏輯：
   - 主引擎：信號日+3~7天，close_price≤limit_price時隔天進場
   - 備位引擎：信號日+5個交易日，close_price≤limit_price時進場
   - 約束：每個ISO周最多入場2個
5. 出場邏輯：
   - 停損：close_price ≤ entry_price × 0.93 (-7%)
   - 停利：+15%啟動，回落10%時出場
   - 時間：42日或90日（日曆日）
   - 滿倉限制：最多同時持倒N個位置（測試3/4/6）
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
print("TDCC 鯨魚策略 v7 完整回測")
print("="*80)

# ================================================================================
# 加載數據
# ================================================================================

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

# 價格（加載完整 OHLCV）
cursor.execute("""
    SELECT stock_code, date, open_price, high_price, low_price, close_price FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
""")
prices = defaultdict(dict)
ohlcv = defaultdict(lambda: defaultdict(dict))
for r in cursor.fetchall():
    code = r['stock_code']
    date = r['date']
    close_price = float(r['close_price']) if r['close_price'] else None
    prices[code][date] = close_price  # 保留舊格式以兼容進場邏輯
    ohlcv[code][date] = {
        'open': float(r['open_price']) if r['open_price'] else None,
        'high': float(r['high_price']) if r['high_price'] else None,
        'low': float(r['low_price']) if r['low_price'] else None,
        'close': close_price,
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

# ================================================================================
# 信號掃描
# ================================================================================

def iso_week_key(date_str):
    """'20260211' → '2026W07'"""
    d = datetime.strptime(date_str, '%Y%m%d')
    iso = d.isocalendar()
    return f'{iso[0]}W{iso[1]:02d}'

def scan_all_signals():
    """掃描全部主引擎和備位引擎信號"""
    main_sigs = []
    backup_sigs = []

    # ──── 主引擎 ────
    for code, grp in tdcc_data.items():
        if len(grp) < 4:
            continue

        for i in range(3, len(grp)):
            # 連升 streak
            streak = 0
            for j in range(i, 0, -1):
                r400_j = float(grp[j]['ratio_400_above'] or 0)
                r400_j1 = float(grp[j-1]['ratio_400_above'] or 0)
                if r400_j > r400_j1:
                    streak += 1
                else:
                    break

            if streak < 3:
                continue

            # 條件檢查
            si = i - streak
            r400_now = float(grp[i]['ratio_400_above'] or 0)
            r400_prev = float(grp[si]['ratio_400_above'] or 0)
            r1000_now = float(grp[i]['ratio_1000_above'] or 0)
            r1000_prev = float(grp[si]['ratio_1000_above'] or 0)

            r400_chg = r400_now - r400_prev
            if r400_chg < 3.0:
                continue

            r1000_chg = r1000_now - r1000_prev
            sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
            if sync < 0.5:
                continue

            holders_now = float(grp[i]['total_holders'] or 0)
            holders_prev = float(grp[si]['total_holders'] or 0)
            holders_chg = (holders_now - holders_prev) / holders_prev * 100 if holders_prev > 0 else 0
            if holders_chg > -2.0:
                continue

            # 股價檢查
            sig_date = grp[i]['date']
            sig_price = prices[code].get(sig_date, 0)
            if sig_price < 300:
                continue

            main_sigs.append({
                'type': 'main',
                'week': iso_week_key(sig_date),
                'code': code,
                'sig_date': sig_date,
                'sig_price': sig_price,
                'limit_price': round(sig_price * 1.03, 2),
                'streak': streak,
                'r400_chg': round(r400_chg, 2),
            })

    # ──── 備位引擎 ────
    for code, grp in tdcc_data.items():
        if len(grp) < 5:
            continue

        for i in range(4, len(grp)):
            # 散戶逃跑檢查
            holders_now = float(grp[i]['total_holders'] or 0)
            holders_4w = float(grp[i-4]['total_holders'] or 0)

            if holders_4w <= 0:
                continue

            flee_pct = (holders_now - holders_4w) / holders_4w * 100
            if flee_pct > -5.0:
                continue

            # 股價檢查
            sig_date = grp[i]['date']
            sig_price = prices[code].get(sig_date) or 0
            if not sig_price or sig_price < 50:
                continue

            # MA20 檢查
            sig_idx = date_to_idx.get(sig_date)
            if sig_idx is None or sig_idx < 20:
                continue

            ma20_prices = []
            for k in range(sig_idx - 20, sig_idx):
                p = prices[code].get(all_dates[k])
                if p:
                    ma20_prices.append(p)

            if len(ma20_prices) < 20:
                continue

            ma20 = sum(ma20_prices) / len(ma20_prices)
            if sig_price < ma20:
                continue

            backup_sigs.append({
                'type': 'backup',
                'week': iso_week_key(sig_date),
                'code': code,
                'sig_date': sig_date,
                'sig_price': sig_price,
                'limit_price': round(sig_price * 1.03, 2),
                'flee_pct': round(flee_pct, 1),
            })

    return main_sigs, backup_sigs

print("\n掃描信號...")
main_sigs, backup_sigs = scan_all_signals()
print(f"✓ 主引擎：{len(main_sigs)} 個")
print(f"✓ 備位引擎：{len(backup_sigs)} 個")

# ================================================================================
# 回測引擎
# ================================================================================

def run_backtest(main_sigs, backup_sigs, max_positions, max_hold_calendar_days):
    """完整回測"""

    # 按周分組和去重
    main_by_week = defaultdict(list)
    for sig in main_sigs:
        main_by_week[sig['week']].append(sig)

    # 每周內排序（連升少的優先，r400_chg多的優先）
    for week in main_by_week:
        main_by_week[week].sort(key=lambda x: (x['streak'], -x['r400_chg']))

    # 備位按周分組
    backup_by_week = defaultdict(list)
    for sig in backup_sigs:
        backup_by_week[sig['week']].append(sig)

    # 有主信號的周不用備位
    for week in main_by_week:
        backup_by_week.pop(week, None)

    # 每周內排序（散戶逃跑最多的優先）
    for week in backup_by_week:
        backup_by_week[week].sort(key=lambda x: x['flee_pct'])

    # ──── 組建進場隊列（每周最多2個） ────
    entry_queue = []

    for week in sorted(main_by_week.keys()):
        for sig in main_by_week[week][:2]:  # 每周最多2個
            entry_queue.append(sig)

    for week in sorted(backup_by_week.keys()):
        for sig in backup_by_week[week][:2]:  # 每周最多2個
            entry_queue.append(sig)

    # ──── 迴圈遍歷日期，模擬交易 ────
    positions = {}  # {code: {...}}
    trades = []
    cash = CAPITAL
    pending_entry = {(sig['code'], sig['sig_date']): sig for sig in entry_queue}

    # 每一日都要處理，包括沒有交易的日期（為了檢查到期）
    start_date_obj = datetime.strptime(all_dates[0], '%Y%m%d')
    end_date_obj = datetime.strptime(all_dates[-1], '%Y%m%d')

    current_date_obj = start_date_obj

    while current_date_obj <= end_date_obj:
        date = current_date_obj.strftime('%Y%m%d')
        date_obj = current_date_obj
        date_idx = date_to_idx.get(date)

        # ──── 1. 出場檢查 ────
        codes_to_exit = []

        for code, pos in list(positions.items()):
            entry_date_obj = datetime.strptime(pos['entry_date'], '%Y%m%d')
            cal_days = (date_obj - entry_date_obj).days

            price = prices[code].get(date)
            ohlcv_data = ohlcv[code].get(date, {})

            should_exit = False
            reason = ''
            pnl_pct = 0

            # 有價格時計算收益
            if price:
                pnl_pct = (price - pos['entry_price']) / pos['entry_price'] * 100

                    # 停損（用收盤價）
                if pnl_pct <= -7.0:
                    should_exit = True
                    reason = '停損'
                # 停利邏輯（用收盤價）
                elif not pos['take_profit_activated'] and pnl_pct >= 15.0:
                    # 首次達到 +15%，啟動停利
                    pos['take_profit_activated'] = True
                    pos['highest_pnl_since_activation'] = pnl_pct
                elif pos['take_profit_activated']:
                    # 追踪最高價
                    pos['highest_pnl_since_activation'] = max(pos['highest_pnl_since_activation'], pnl_pct)
                    # 檢查回落 10%
                    if pos['highest_pnl_since_activation'] - pnl_pct >= 10.0:
                        should_exit = True
                        reason = '停利'

            # 時間限制（無條件檢查，不需要有價格）
            if not should_exit and cal_days >= max_hold_calendar_days:
                should_exit = True
                reason = '到期'
                # 如果沒有當日價格，用最近的價格
                if not price and date_idx is not None:
                    for k in range(date_idx - 1, -1, -1):
                        p = prices[code].get(all_dates[k])
                        if p:
                            price = p
                            break

            if should_exit and price:
                # 沒有當日價格時，找最近的過去價格
                if not price and date_idx is not None:
                    for k in range(date_idx - 1, -1, -1):
                        p = prices[code].get(all_dates[k])
                        if p:
                            price = p
                            break

            if should_exit and price:
                net_pnl_pct = pnl_pct - (SELL_FEE + SELL_TAX) * 100
                pnl_amt = pos['invested'] * net_pnl_pct / 100
                cash += pos['invested'] + pnl_amt

                trades.append({
                    '股票': code,
                    '引擎': pos['engine'],
                    '進場日期': pos['entry_date'],
                    '進場價格': f"{pos['entry_price']:.2f}",
                    '出場日期': date,
                    '出場價格': f"{price:.2f}",
                    '日曆天數': cal_days,
                    '收益率%': f"{net_pnl_pct:+.2f}%",
                    '收益金額': f"NT${pnl_amt:+,.0f}",
                    '出場原因': reason,
                })
                codes_to_exit.append(code)

        for code in codes_to_exit:
            del positions[code]

        # ──── 2. 進場檢查 ────
        sigs_to_remove = []

        # 只在有交易數據的日期才檢查進場
        if date_idx is not None:
            for (code, sig_date), sig in list(pending_entry.items()):
                if code in positions or len(positions) >= max_positions:
                    continue

                sig_idx = date_to_idx.get(sig_date)
                if sig_idx is None:
                    continue

                days_since = date_idx - sig_idx

                # 主引擎進場條件
                if sig['type'] == 'main':
                    if 3 <= days_since <= 7:
                        price = prices[code].get(date)
                        if price and price <= sig['limit_price']:
                            # 隔天進場
                            if date_idx + 1 < len(all_dates):
                                entry_date = all_dates[date_idx + 1]
                                entry_price = prices[code].get(entry_date, price)
                            else:
                                entry_date = date
                                entry_price = price

                            per_pos = CAPITAL // max_positions
                            shares = int(per_pos / (entry_price * (1 + BUY_FEE)))

                            if shares > 0:
                                invested = shares * entry_price * (1 + BUY_FEE)
                                if invested <= cash:
                                    positions[code] = {
                                        'entry_date': entry_date,
                                        'entry_price': entry_price,
                                        'invested': invested,
                                        'engine': 'main',
                                        'take_profit_activated': False,
                                        'highest_pnl_since_activation': 0,
                                    }
                                    cash -= invested
                                    sigs_to_remove.append((code, sig_date))

                    # 超過7天放棄
                    elif days_since > 7:
                        sigs_to_remove.append((code, sig_date))

                # 備位引擎進場條件
                elif sig['type'] == 'backup':
                    if days_since == 5:
                        price = prices[code].get(date)
                        if price and price <= sig['limit_price']:
                            per_pos = CAPITAL // max_positions
                            shares = int(per_pos / (price * (1 + BUY_FEE)))

                            if shares > 0:
                                invested = shares * price * (1 + BUY_FEE)
                                if invested <= cash:
                                    positions[code] = {
                                        'entry_date': date,
                                        'entry_price': price,
                                        'invested': invested,
                                        'engine': 'backup',
                                        'take_profit_activated': False,
                                        'highest_pnl_since_activation': 0,
                                    }
                                    cash -= invested
                                    sigs_to_remove.append((code, sig_date))

                    # 超過5天放棄
                    elif days_since > 5:
                        sigs_to_remove.append((code, sig_date))

        for key in sigs_to_remove:
            pending_entry.pop(key, None)

        current_date_obj += timedelta(days=1)

    conn.close()
    return pd.DataFrame(trades)

# ================================================================================
# 執行回測 - 多個配置
# ================================================================================

print("\n" + "="*80)
print("執行回測...")
print("="*80)

configs = [
    (42, 3, "6週+3個持倉"),
    (42, 4, "6週+4個持倉"),
    (42, 6, "6週+6個持倉"),
    (90, 3, "90天+3個持倉"),
    (90, 4, "90天+4個持倉"),
    (90, 6, "90天+6個持倉"),
]

results_summary = []

for hold_days, max_pos, label in configs:
    print(f"\n【{label}】執行中...")

    trades_df = run_backtest(main_sigs, backup_sigs, max_pos, hold_days)

    output_file = f'/tmp/trading_reports/完整版_{label}.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')

    if len(trades_df) > 0:
        total_pnl_str = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float)
        total_pnl = total_pnl_str.sum()
        max_days = trades_df['日曆天數'].max()

        win_count = (total_pnl_str > 0).sum()
        win_rate = win_count / len(trades_df) * 100

        print(f"  ✓ {len(trades_df):3d} 筆交易")
        print(f"    總利潤：NT${total_pnl:+,.0f}")
        print(f"    勝率：{win_rate:.1f}% ({win_count}/{len(trades_df)})")
        print(f"    最大持倒：{max_days} 日")

        results_summary.append({
            '配置': label,
            '交易數': len(trades_df),
            '勝率': f"{win_rate:.1f}%",
            '總利潤': f"NT${total_pnl:+,.0f}",
            '最大持倒': f"{max_days}日"
        })
    else:
        print(f"  ⚠️  無交易")
        results_summary.append({
            '配置': label,
            '交易數': 0,
            '勝率': '-',
            '總利潤': 'NT$0',
            '最大持倒': '-'
        })

print("\n" + "="*80)
print("回測完成")
print("="*80)

# 輸出摘要
summary_df = pd.DataFrame(results_summary)
print("\n【摘要】")
print(summary_df.to_string(index=False))

print("\n✅ 所有檔案已存放在 /tmp/trading_reports/")

