#!/usr/bin/env python3
"""
TDCC 鯨魚策略 v7 嚴格合規回測

完整規格實現：
1. 主引擎：連升3週+r400↑3%+同步≥50%+散戶↓≥2%+股價≥300
2. 備位引擎 v2 (STRICT)：
   - 3週散戶↓≥15%
   - 同時大戶↑≥2%
   - 股價≥50元 (嚴格檢查)
   - 站上MA20 (嚴格檢查)
3. 主備位去重：有主信號的周不用備位
4. 進場邏輯：
   - 主引擎：信號日+3~7天，close_price≤limit_price時隔天進場
   - 備位引擎：信號日+5個交易日，close_price≤limit_price時進場
   - 約束：每個ISO周最多入場2個
5. 出場邏輯：
   - 停損：close_price ≤ entry_price × 0.93 (-7%)
   - 停利：+15%啟動，回落10%時出場
   - 時間：42日或90日（日曆日）
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
print("TDCC 鯨魚策略 v7 嚴格合規回測")
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

# 價格
print("  → 載入價格數據...")
cursor.execute("""
    SELECT stock_code, date, close_price FROM daily_prices
    WHERE date >= '20220101' AND date <= '20251231'
    ORDER BY stock_code, date
""")
prices = defaultdict(dict)
for r in cursor.fetchall():
    prices[r['stock_code']][r['date']] = float(r['close_price'])

# TDCC 數據
print("  → 載入 TDCC 數據...")
cursor.execute("""
    SELECT stock_code, date, ratio_400_above, ratio_1000_above, total_holders
    FROM holdings
    WHERE stock_code NOT LIKE '00%'
    ORDER BY stock_code, date
""")
tdcc_data = defaultdict(list)
for r in cursor.fetchall():
    tdcc_data[r['stock_code']].append(r)

# ================================================================================
# 計算 MA20 (20交易日簡單移動平均)
# ================================================================================

print("  → 計算 MA20 (20 交易日簡單移動平均)...")

ma20 = defaultdict(dict)

for code in prices:
    code_prices = []
    code_dates = []

    # 按日期排序該股票的價格
    for date in sorted(prices[code].keys()):
        code_prices.append(prices[code][date])
        code_dates.append(date)

    # 計算 MA20：每個日期的前 20 個交易日平均
    for i in range(len(code_prices)):
        if i < 19:
            # 不足 20 日，先計算已有的
            ma = sum(code_prices[:i+1]) / (i+1)
        else:
            # 足夠 20 日
            ma = sum(code_prices[i-19:i+1]) / 20

        ma20[code][code_dates[i]] = ma

print(f"✓ {len(all_dates)} 個交易日")
print(f"✓ {len(prices)} 支股票有價格數據")
print(f"✓ {len(tdcc_data)} 支股票有 TDCC 數據")
print(f"✓ {len(ma20)} 支股票有 MA20 數據")

# ================================================================================
# 信號掃描 (嚴格合規版)
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

    # ──── 主引擎 (連升3週+r400↑3%+同步≥50%+散戶↓≥2%+股價≥300) ────
    print("\n掃描主引擎信號...")
    main_count = 0

    for code, grp in tdcc_data.items():
        if len(grp) < 4:
            continue

        for i in range(3, len(grp)):
            # 連升 streak (ratio_400_above)
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

            # 股價檢查 (≥300)
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
            main_count += 1

    print(f"  ✓ 主引擎信號掃描完成：{main_count} 個")

    # ──── 備位引擎 v2 (STRICT 檢查所有4個條件) ────
    print("\n掃描備位引擎信號...")
    backup_count = 0
    backup_filtered = {}  # 追蹤被過濾的信號

    for code, grp in tdcc_data.items():
        if len(grp) < 4:
            continue

        for i in range(3, len(grp)):
            sig_date = grp[i]['date']

            # ──── 條件1：3週散戶減少≥15% ────
            holders_now = float(grp[i]['total_holders'] or 0)
            holders_3w = float(grp[i-3]['total_holders'] or 0)

            if holders_3w <= 0:
                continue

            flee_pct = (holders_now - holders_3w) / holders_3w * 100
            if flee_pct > -15.0:
                continue

            # ──── 條件2：大戶增加≥2% ────
            r400_now = float(grp[i]['ratio_400_above'] or 0)
            r400_3w = float(grp[i-3]['ratio_400_above'] or 0)
            r400_chg = r400_now - r400_3w
            if r400_chg < 2.0:
                continue

            # ──── 條件3：股價≥50元 (STRICT) ────
            sig_price = prices[code].get(sig_date, 0)
            if sig_price < 50:
                if code not in backup_filtered:
                    backup_filtered[code] = []
                backup_filtered[code].append({
                    'date': sig_date,
                    'price': sig_price,
                    'reason': 'price < 50'
                })
                continue

            # ──── 條件4：站上 MA20 (STRICT) ────
            stock_ma20 = ma20[code].get(sig_date)
            if stock_ma20 is None or sig_price < stock_ma20:
                if code not in backup_filtered:
                    backup_filtered[code] = []
                backup_filtered[code].append({
                    'date': sig_date,
                    'price': sig_price,
                    'ma20': stock_ma20,
                    'reason': 'price < MA20' if stock_ma20 else 'no MA20'
                })
                continue

            # ──── 所有條件都通過 ────
            backup_sigs.append({
                'type': 'backup',
                'week': iso_week_key(sig_date),
                'code': code,
                'sig_date': sig_date,
                'sig_price': sig_price,
                'ma20': stock_ma20,
                'limit_price': round(sig_price * 1.03, 2),
                'flee_pct': round(flee_pct, 1),
                'r400_chg': round(r400_chg, 2),
            })
            backup_count += 1

    print(f"  ✓ 備位引擎信號掃描完成：{backup_count} 個")

    # 統計被過濾的備位信號
    if backup_filtered:
        print("\n備位信號過濾統計：")
        for code in sorted(backup_filtered.keys())[:5]:  # 顯示前5個股票
            print(f"  {code}: {len(backup_filtered[code])} 個被過濾")

    return main_sigs, backup_sigs

print("\n" + "="*80)
print("信號掃描階段")
print("="*80)
main_sigs, backup_sigs = scan_all_signals()

print(f"\n【信號彙總】")
print(f"  主引擎：{len(main_sigs)} 個信號")
print(f"  備位引擎：{len(backup_sigs)} 個信號")

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

            should_exit = False
            reason = ''
            pnl_pct = 0

            # 有價格時計算收益
            if price:
                pnl_pct = (price - pos['entry_price']) / pos['entry_price'] * 100

                # 停損
                if pnl_pct <= -7.0:
                    should_exit = True
                    reason = '停損'
                # 停利邏輯
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
print("執行回測")
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

    # 創建輸出目錄
    Path('/tmp/trading_reports').mkdir(exist_ok=True)
    output_file = f'/tmp/trading_reports/嚴格合規版_{label}.csv'
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
print("回測完成 (嚴格合規版)")
print("="*80)

# 輸出摘要
summary_df = pd.DataFrame(results_summary)
print("\n【摘要】")
print(summary_df.to_string(index=False))

print("\n✅ 所有檔案已存放在 /tmp/trading_reports/")
print("✅ 嚴格檢查了所有備位引擎條件：股價≥50、站上MA20")
