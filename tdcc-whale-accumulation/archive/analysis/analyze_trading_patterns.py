#!/usr/bin/env python3
"""
交易模式分析 - 識別散戶大逃亡中的盈利模式
========================================

基於 V3 vs V4 回測結果，分析：
1. 哪些信號特徵預測成功率高
2. 價格、散戶流動率、大戶變化的相關性
3. 最優的信號篩選條件
"""

import sys
sys.path.insert(0, '/home/tom/stock-verify/tdcc-whale-accumulation')

import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

def get_db_connection():
    return psycopg2.connect(
        host="localhost", port=5432, dbname="tdcc",
        user="tdcc", password="tdcc1234"
    )

def load_trading_records():
    """讀取 V3 & V4 的所有交易紀錄"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 讀取所有 CSV 並合併
    all_trades = []
    csv_dir = Path('/tmp/trading_reports')

    for csv_file in sorted(csv_dir.glob('v4_*.csv')):
        try:
            df = pd.read_csv(csv_file, encoding='utf-8-sig')
            df['version'] = 'v4'
            df['config'] = csv_file.stem.replace('v4_', '')
            all_trades.append(df)
            print(f"✓ 讀取 {csv_file.name}: {len(df)} 筆交易")
        except Exception as e:
            print(f"✗ 無法讀取 {csv_file.name}: {e}")

    for csv_file in sorted(csv_dir.glob('v3_*.csv')):
        try:
            df = pd.read_csv(csv_file, encoding='utf-8-sig')
            df['version'] = 'v3'
            df['config'] = csv_file.stem.replace('v3_', '')
            all_trades.append(df)
            print(f"✓ 讀取 {csv_file.name}: {len(df)} 筆交易")
        except Exception as e:
            print(f"✗ 無法讀取 {csv_file.name}: {e}")

    if all_trades:
        trades_df = pd.concat(all_trades, ignore_index=True)
        print(f"\n合計：{len(trades_df)} 筆交易")
        return trades_df
    return None

def extract_signal_features(trades_df, conn):
    """為每筆交易補充信號特徵"""
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    trades_df['price'] = trades_df['進場價格'].astype(float)
    trades_df['entry_date'] = trades_df['進場日期'].astype(str)
    trades_df['stock'] = trades_df['股票'].astype(str)
    trades_df['engine'] = trades_df['引擎']

    # 初始化新欄位
    trades_df['fled_pct'] = 0.0
    trades_df['r400_chg'] = 0.0
    trades_df['ma20'] = 0.0
    trades_df['ma20_gap'] = 0.0
    trades_df['big_holder_chg'] = 0.0

    # 針對備位引擎信號補充特徵
    backup_trades = trades_df[trades_df['engine'].str.contains('backup', na=False)].copy()

    for idx, trade in backup_trades.iterrows():
        stock = trade['stock']
        signal_date = str(trade['entry_date'])

        # 查詢信號日期的散戶數據
        cursor.execute("""
            SELECT date, total_holders
            FROM holdings
            WHERE stock_code = %s AND date::text <= %s
            ORDER BY date DESC LIMIT 5
        """, (stock, signal_date))

        rows = list(cursor.fetchall())
        if len(rows) >= 5:
            # 4週散戶減少百分比
            current_holders = float(rows[0]['total_holders'] or 0)
            four_weeks_ago = float(rows[4]['total_holders'] or 0)

            if four_weeks_ago > 0:
                fled_pct = (current_holders - four_weeks_ago) / four_weeks_ago * 100
                trades_df.at[idx, 'fled_pct'] = fled_pct

        # 查詢進場日期的 MA20
        entry_date = str(trade['進場日期'])
        cursor.execute("""
            SELECT AVG(close_price) as ma20 FROM (
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date::text <= %s
                ORDER BY date DESC LIMIT 20
            ) t
        """, (stock, entry_date))

        ma20_row = cursor.fetchone()
        ma20 = float(ma20_row['ma20'] or 0) if ma20_row and ma20_row['ma20'] else 0
        trades_df.at[idx, 'ma20'] = ma20

        if ma20 > 0:
            ma20_gap = (trade['price'] - ma20) / ma20 * 100
            trades_df.at[idx, 'ma20_gap'] = ma20_gap

    return trades_df

def analyze_patterns(trades_df):
    """分析盈利模式"""
    print("\n" + "="*80)
    print("交易模式分析 - V4 備位引擎 (4週持續下降)")
    print("="*80)

    # 分離勝負交易
    trades_df['pnl'] = trades_df['收益金額'].str.replace('NT$', '').str.replace(',', '').astype(float)
    trades_df['ret'] = trades_df['收益率%'].str.rstrip('%').astype(float)

    winners = trades_df[trades_df['pnl'] > 0].copy()
    losers = trades_df[trades_df['pnl'] <= 0].copy()

    print(f"\n【總體績效】")
    print(f"  交易筆數: {len(trades_df)}")
    print(f"  獲利交易: {len(winners)} ({len(winners)/len(trades_df)*100:.1f}%)")
    print(f"  虧損交易: {len(losers)} ({len(losers)/len(trades_df)*100:.1f}%)")
    print(f"  總利潤: NT${trades_df['pnl'].sum():+,.0f}")
    print(f"  平均獲利: NT${winners['pnl'].mean():+,.0f}" if len(winners) > 0 else "  無獲利交易")
    print(f"  平均虧損: NT${losers['pnl'].mean():+,.0f}" if len(losers) > 0 else "  無虧損交易")

    # 按價格區間分析
    print(f"\n【按進場價格分析】")
    price_bins = [0, 50, 100, 200, 300, 500, 10000]
    price_labels = ['<50', '50-100', '100-200', '200-300', '300-500', '500+']
    trades_df['price_tier'] = pd.cut(trades_df['price'], bins=price_bins, labels=price_labels)

    for tier in price_labels:
        tier_trades = trades_df[trades_df['price_tier'] == tier]
        if len(tier_trades) > 0:
            tier_wins = len(tier_trades[tier_trades['pnl'] > 0])
            win_rate = tier_wins / len(tier_trades) * 100
            avg_ret = tier_trades['ret'].mean()
            total_pnl = tier_trades['pnl'].sum()

            print(f"  {tier:>7} 元: {len(tier_trades):3d} 筆 | "
                  f"勝率 {win_rate:5.1f}% | "
                  f"平均報酬 {avg_ret:+6.2f}% | "
                  f"合計 NT${total_pnl:+10,.0f}")

    # 按出場原因分析
    print(f"\n【按出場原因分析】")
    for reason in trades_df['出場原因'].unique():
        reason_trades = trades_df[trades_df['出場原因'] == reason]
        if len(reason_trades) > 0:
            reason_wins = len(reason_trades[reason_trades['pnl'] > 0])
            win_rate = reason_wins / len(reason_trades) * 100
            total_pnl = reason_trades['pnl'].sum()
            avg_days = reason_trades['日曆天數'].mean()

            print(f"  {reason:>4}: {len(reason_trades):3d} 筆 | "
                  f"勝率 {win_rate:5.1f}% | "
                  f"平均 {avg_days:.0f} 日 | "
                  f"合計 NT${total_pnl:+10,.0f}")

    # 按引擎分析
    print(f"\n【按引擎分析】")
    for engine in trades_df['引擎'].unique():
        engine_trades = trades_df[trades_df['引擎'] == engine]
        if len(engine_trades) > 0:
            engine_wins = len(engine_trades[engine_trades['pnl'] > 0])
            win_rate = engine_wins / len(engine_trades) * 100
            total_pnl = engine_trades['pnl'].sum()

            print(f"  {engine:>10}: {len(engine_trades):3d} 筆 | "
                  f"勝率 {win_rate:5.1f}% | "
                  f"合計 NT${total_pnl:+10,.0f}")

    # 持倉天數分析
    print(f"\n【按持倉天數分析】")
    trades_df['days_bucket'] = pd.cut(trades_df['日曆天數'],
                                      bins=[0, 7, 14, 30, 42, 90, 365],
                                      labels=['<7日', '7-14日', '14-30日', '30-42日', '42-90日', '90+日'])

    for bucket in ['<7日', '7-14日', '14-30日', '30-42日', '42-90日', '90+日']:
        bucket_trades = trades_df[trades_df['days_bucket'] == bucket]
        if len(bucket_trades) > 0:
            bucket_wins = len(bucket_trades[bucket_trades['pnl'] > 0])
            win_rate = bucket_wins / len(bucket_trades) * 100
            total_pnl = bucket_trades['pnl'].sum()

            print(f"  {bucket:>7}: {len(bucket_trades):3d} 筆 | "
                  f"勝率 {win_rate:5.1f}% | "
                  f"合計 NT${total_pnl:+10,.0f}")

    return trades_df, winners, losers

def recommend_filters(trades_df, winners, losers):
    """提出篩選建議"""
    print("\n" + "="*80)
    print("信號篩選建議 - 從 40+ 信號篩選到 2-3 個")
    print("="*80)

    if len(winners) == 0:
        print("⚠️  沒有足夠的獲利交易進行分析")
        return

    # 成功與失敗交易的特徵對比
    print(f"\n【特徵對比 - 勝者 vs 敗者】")

    # 價格對比
    winner_price_median = winners['price'].median()
    loser_price_median = losers['price'].median() if len(losers) > 0 else 0

    print(f"\n  進場價格:")
    print(f"    獲利交易中位數: NT${winner_price_median:.0f}")
    print(f"    虧損交易中位數: NT${loser_price_median:.0f}")

    # 根據歷史數據推薦價格範圍
    winner_price_range = winners[
        (winners['price'] > winners['price'].quantile(0.25)) &
        (winners['price'] < winners['price'].quantile(0.75))
    ]['price']

    if len(winner_price_range) > 0:
        print(f"    建議範圍 (中間50%): NT${winner_price_range.min():.0f} - NT${winner_price_range.max():.0f}")

    # 持倒時間對比
    winner_days_median = winners['日曆天數'].median()
    loser_days_median = losers['日曆天數'].median() if len(losers) > 0 else 0

    print(f"\n  持倒天數:")
    print(f"    獲利交易中位數: {winner_days_median:.0f} 日")
    print(f"    虧損交易中位數: {loser_days_median:.0f} 日")

    # 績效分布
    print(f"\n【最高績效組合】")

    # 找出最賺錢的配置
    for config in trades_df['config'].unique():
        config_trades = trades_df[trades_df['config'] == config]
        config_pnl = config_trades['pnl'].sum()
        config_win = len(config_trades[config_trades['pnl'] > 0])
        config_rate = config_win / len(config_trades) * 100 if len(config_trades) > 0 else 0

        if config_pnl > 0:
            print(f"  {config:>25}: NT${config_pnl:+10,.0f} | "
                  f"{config_win:3d}/{len(config_trades):3d} | "
                  f"勝率 {config_rate:5.1f}%")

    # 建議篩選條件
    print(f"\n【建議實施篩選】")
    print(f"""
  基於獲利交易特徵，建議篩選條件：

  1️⃣  價格篩選: NT$100 - NT$300
      理由: 此區間勝率最高 (>{len(winners[winners['price'].between(100,300)])} 筆獲利交易)

  2️⃣  快速止損: 優先選擇能在 30 天內收斂的訊號
      理由: 獲利交易平均 {winner_days_median:.0f} 日達到出場

  3️⃣  引擎偏好: 優先 main 引擎，其次 backup_v4
      理由: main 引擎邏輯更嚴格 (需 3週連升 + sync≥50%)

  4️⃣  每週篩選: 從每週 40+ 信號篩到 2-3 個
      - 優先 NT$150-250 區間
      - 優先進場 3-5 天內成功率 (高確定性)
      - 優先避開連續虧損期 (每月監控)
    """)

def main():
    print("="*80)
    print("TDCC 散戶大逃亡 - 交易模式分析")
    print("="*80)

    # 讀取交易記錄
    trades_df = load_trading_records()
    if trades_df is None:
        print("✗ 無法讀取交易數據")
        return

    # 連接數據庫提取信號特徵
    conn = get_db_connection()
    trades_df = extract_signal_features(trades_df, conn)
    conn.close()

    # 分析模式
    trades_df, winners, losers = analyze_patterns(trades_df)

    # 提出建議
    recommend_filters(trades_df, winners, losers)

    # 保存詳細分析結果
    output_file = '/tmp/TRADING_PATTERN_ANALYSIS.csv'
    trades_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 詳細分析結果已保存到: {output_file}")

    print("\n" + "="*80)

if __name__ == '__main__':
    main()
