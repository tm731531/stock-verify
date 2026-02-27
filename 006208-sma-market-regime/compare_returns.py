#!/usr/bin/env python3
"""
比較簡單系統 vs 定期定額的報酬
"""

import pandas as pd
import numpy as np


def main():
    # 加載數據
    df = pd.read_csv('data/006208_historical.csv', index_col='Date', parse_dates=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

    # 計算 SMA
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()

    print("=" * 100)
    print("策略對比：簡單 SMA 系統 vs 定期定額投資")
    print("=" * 100)

    print(f"\n📊 回測期間: {df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"💰 起始價格: ${df['Close'].iloc[0]:.2f}")
    print(f"💰 結束價格: ${df['Close'].iloc[-1]:.2f}")

    # ===== 方案 1: 簡單 SMA 系統 =====
    initial_capital = 100000  # 初始 10 萬
    monthly_invest = 2000     # 每月投入 2000

    cash = initial_capital
    shares = 0
    portfolio_value_sma = []
    dates_sma = []
    monthly_count = 0

    print(f"\n{'-' * 100}")
    print("方案 1: 簡單 SMA 系統 (SMA50 > SMA200 時進場)")
    print(f"{'-' * 100}")
    print(f"初始資本: ${initial_capital:,.0f}")
    print(f"每月額外投入: ${monthly_invest:,.0f}")

    prev_month = None
    for i in range(200, len(df)):
        date = df.index[i]
        price = df.iloc[i]['Close']
        sma50 = df.iloc[i]['SMA_50']
        sma200 = df.iloc[i]['SMA_200']

        if pd.isna(sma50) or pd.isna(sma200):
            continue

        # 每月投入 2000 現金
        current_month = date.month
        if prev_month != current_month:
            cash += monthly_invest
            monthly_count += 1
            prev_month = current_month

        # 根據 SMA 訊號進場或持有現金
        if sma50 > sma200:
            # 進場：用所有現金買進
            if cash >= price:
                new_shares = cash / price
                shares += new_shares
                cash = 0
        else:
            # 空頭：保持現金，賣出所有持倉
            cash += shares * price
            shares = 0

        # 計算投組價值
        portfolio_value = cash + shares * price
        portfolio_value_sma.append(portfolio_value)
        dates_sma.append(date)

    # ===== 方案 2: 純定期定額 =====
    cash_dca = initial_capital
    shares_dca = 0
    portfolio_value_dca = []
    dates_dca = []

    print(f"\n{'-' * 100}")
    print("方案 2: 純定期定額 (每月定額買進，從不賣出)")
    print(f"{'-' * 100}")
    print(f"初始資本: ${initial_capital:,.0f}")
    print(f"每月額外投入: ${monthly_invest:,.0f}")

    prev_month = None
    for i in range(200, len(df)):
        date = df.index[i]
        price = df.iloc[i]['Close']

        # 每月投入 2000 現金
        current_month = date.month
        if prev_month != current_month:
            cash_dca += monthly_invest
            prev_month = current_month

        # 永遠定額買進
        if cash_dca >= price:
            new_shares = cash_dca / price
            shares_dca += new_shares
            cash_dca = 0

        # 計算投組價值
        portfolio_value = cash_dca + shares_dca * price
        portfolio_value_dca.append(portfolio_value)
        dates_dca.append(date)

    # ===== 結果對比 =====
    print(f"\n{'-' * 100}")
    print("📊 最終成績")
    print(f"{'-' * 100}")

    final_sma = portfolio_value_sma[-1]
    final_dca = portfolio_value_dca[-1]
    total_invested = initial_capital + (monthly_count * monthly_invest)

    print(f"\n總投入金額: ${total_invested:,.0f}")
    print(f"投入期間: {monthly_count} 個月")

    print(f"\n🎯 方案 1 (SMA 系統):")
    print(f"  最終資產: ${final_sma:,.2f}")
    print(f"  報酬率: {((final_sma - total_invested) / total_invested * 100):+.2f}%")
    print(f"  絕對獲利: ${final_sma - total_invested:+,.2f}")

    print(f"\n📅 方案 2 (定期定額):")
    print(f"  最終資產: ${final_dca:,.2f}")
    print(f"  報酬率: {((final_dca - total_invested) / total_invested * 100):+.2f}%")
    print(f"  絕對獲利: ${final_dca - total_invested:+,.2f}")

    diff = final_sma - final_dca
    diff_pct = (diff / final_dca) * 100

    print(f"\n⚖️ 差異:")
    print(f"  SMA 系統 vs 定期定額: ${diff:+,.2f}")
    print(f"  相對差異: {diff_pct:+.2f}%")

    if diff > 0:
        print(f"  ✅ SMA 系統贏了 ${diff:,.2f}")
    else:
        print(f"  ⚠️ 定期定額贏了 ${abs(diff):,.2f}")

    # ===== 分時期對比 =====
    print(f"\n{'-' * 100}")
    print("各時期表現對比")
    print(f"{'-' * 100}")

    periods = {
        '2020 (COVID)': ('2020-01-01', '2020-12-31'),
        '2021 (恢復)': ('2021-01-01', '2021-12-31'),
        '2022 (空頭)': ('2022-01-01', '2022-12-31'),
        '2023 (盤整)': ('2023-01-01', '2023-12-31'),
        '2024 (反轉)': ('2024-01-01', '2024-12-31'),
        '2025 (上升)': ('2025-01-01', '2025-12-31'),
    }

    for period_name, (start, end) in periods.items():
        sma_period = [v for d, v in zip(dates_sma, portfolio_value_sma) if start <= d.strftime('%Y-%m-%d') <= end]
        dca_period = [v for d, v in zip(dates_dca, portfolio_value_dca) if start <= d.strftime('%Y-%m-%d') <= end]

        if len(sma_period) > 0 and len(dca_period) > 0:
            sma_start = sma_period[0]
            sma_end = sma_period[-1]
            dca_start = dca_period[0]
            dca_end = dca_period[-1]

            sma_ret = ((sma_end - sma_start) / sma_start) * 100
            dca_ret = ((dca_end - dca_start) / dca_start) * 100

            print(f"\n{period_name}:")
            print(f"  SMA系統: {sma_ret:+.2f}%  (${sma_start:,.0f} → ${sma_end:,.0f})")
            print(f"  定期定額: {dca_ret:+.2f}%  (${dca_start:,.0f} → ${dca_end:,.0f})")
            print(f"  差異: {sma_ret - dca_ret:+.2f}%", "✅ SMA贏" if sma_ret > dca_ret else "⚠️ 定期定額贏")

    # ===== 關鍵洞察 =====
    print(f"\n{'=' * 100}")
    print("💡 關鍵洞察")
    print(f"{'=' * 100}")

    # 計算 SMA 系統持倉的時間百分比
    in_position = sum(1 for d, v in zip(dates_sma, portfolio_value_sma) if d.month != 1)  # 簡化計算
    sma_dates = len(dates_sma)
    exposure = (in_position / sma_dates * 100) if sma_dates > 0 else 0

    print(f"""
✅ SMA 系統的優點：
   1. 自動躲避空頭（2022 年保護）
   2. 只在上升趨勢進場
   3. 無需時刻監控

⚠️ SMA 系統的缺點：
   1. 可能錯過底部反彈
   2. 進場時機較晚
   3. 手續費和稅費較多（頻繁交易）

✅ 定期定額的優點：
   1. 簡單，完全自動
   2. 不需要預測市場
   3. 心理壓力小
   4. 手續費最少

⚠️ 定期定額的缺點：
   1. 空頭期間仍然買入
   2. 2022 年虧損更多
   3. 可能買到最高點
""")

    print(f"{'=' * 100}\n")


if __name__ == '__main__':
    main()
