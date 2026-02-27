#!/usr/bin/env python3
"""
市場制度判斷系統 - 3條規則驗證
用簡單規則識別：空頭警訊、空頭進行、進場機會
"""

import pandas as pd
import numpy as np


def calculate_indicators(df):
    """計算技術指標"""
    # SMA
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()

    # ATR (波動率)
    df['TR'] = np.maximum(
        df['High'] - df['Low'],
        np.maximum(
            abs(df['High'] - df['Close'].shift(1)),
            abs(df['Low'] - df['Close'].shift(1))
        )
    )
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df['ATR_MA'] = df['ATR'].rolling(window=20).mean()

    # 日跌幅
    df['Daily_Return'] = df['Close'].pct_change()

    return df


def detect_market_regime(df):
    """
    檢測市場制度和訊號

    Returns:
        DataFrame with signals:
        - regime: 'bull', 'bear', 'transition'
        - signal: 'warning', 'hold', 'entry'
        - reason: 詳細原因
    """

    df['regime'] = 'unknown'
    df['signal'] = 'hold'
    df['reason'] = ''
    df['volatility_level'] = 'normal'

    for i in range(200, len(df)):
        close = df.iloc[i]['Close']
        sma50 = df.iloc[i]['SMA_50']
        sma200 = df.iloc[i]['SMA_200']
        atr = df.iloc[i]['ATR']
        atr_ma = df.iloc[i]['ATR_MA']
        daily_ret = df.iloc[i]['Daily_Return']

        if pd.isna(sma50) or pd.isna(sma200) or pd.isna(atr):
            continue

        # ===== 規則 1: 波動率爆炸 警訊 =====
        if atr > atr_ma * 1.5:
            df.at[i, 'volatility_level'] = 'high'

            if daily_ret < -0.03:  # 單日跌 > 3%
                df.at[i, 'signal'] = 'warning'
                df.at[i, 'reason'] = f'波動爆炸 + 跌幅 {daily_ret*100:.1f}%'

        # ===== 規則 2: 趨勢確認 =====
        if sma50 < sma200:
            df.at[i, 'regime'] = 'bear'
            df.at[i, 'signal'] = 'hold'
            if df.at[i, 'reason'] == '':
                df.at[i, 'reason'] = '空頭進行中: SMA50 < SMA200'
        else:
            df.at[i, 'regime'] = 'bull'

        # ===== 規則 3: 進場機會 (空頭結束) =====
        # 條件: SMA50 > SMA200 且波動率開始下降
        if i > 0:
            prev_atr = df.iloc[i-1]['ATR']

            if (sma50 > sma200 and
                pd.notna(prev_atr) and
                atr < prev_atr and
                atr < atr_ma * 1.2):  # 波動率回到相對正常

                df.at[i, 'signal'] = 'entry'
                df.at[i, 'regime'] = 'bull'
                df.at[i, 'reason'] = f'黃金交叉 + 波動下降 (ATR: {atr:.2f})'

    return df


def analyze_regimes(df):
    """分析市場制度和訊號發生的時間"""

    print("=" * 100)
    print("市場制度判斷系統 - 3 規則驗證結果")
    print("=" * 100)

    start_date = df.index[0] if hasattr(df.index[0], 'date') else pd.Timestamp(df.index[0]).date()
    end_date = df.index[-1] if hasattr(df.index[-1], 'date') else pd.Timestamp(df.index[-1]).date()
    print(f"\n📊 回測期間: {start_date} → {end_date}")
    print(f"💰 起始價格: ${df['Close'].iloc[0]:.2f}")
    print(f"💰 結束價格: ${df['Close'].iloc[-1]:.2f}")
    print(f"📈 總漲幅: {((df['Close'].iloc[-1] / df['Close'].iloc[0]) - 1) * 100:+.1f}%")

    # 統計警訊
    warnings = df[df['signal'] == 'warning']
    entries = df[df['signal'] == 'entry']
    bears = df[df['regime'] == 'bear']

    print(f"\n{'-' * 100}")
    print("訊號統計")
    print(f"{'-' * 100}")
    print(f"🚨 空頭警訊次數: {len(warnings)}")
    print(f"✅ 進場機會次數: {len(entries)}")
    print(f"📉 空頭天數: {len(bears)} / {len(df)} ({len(bears)/len(df)*100:.1f}%)")

    # 詳細事件列表
    print(f"\n{'-' * 100}")
    print("🚨 空頭警訊事件")
    print(f"{'-' * 100}")

    if len(warnings) > 0:
        for idx, row in warnings.iterrows():
            print(f"{idx.date()}: {row['reason']}")
            print(f"  價格: ${row['Close']:.2f}, ATR: {row['ATR']:.2f}, 波動率: {row['ATR']/row['ATR_MA']:.2f}x")
    else:
        print("無")

    # 進場機會
    print(f"\n{'-' * 100}")
    print("✅ 進場機會事件")
    print(f"{'-' * 100}")

    if len(entries) > 0:
        for idx, row in entries.iterrows():
            print(f"{idx.date()}: {row['reason']}")
            print(f"  價格: ${row['Close']:.2f}, SMA50: ${row['SMA_50']:.2f}, SMA200: ${row['SMA_200']:.2f}")
    else:
        print("無")

    # 分析各時期
    print(f"\n{'-' * 100}")
    print("各時期分析")
    print(f"{'-' * 100}")

    periods = {
        '2020': ('2020-01-01', '2020-12-31'),
        '2021': ('2021-01-01', '2021-12-31'),
        '2022 (危險期)': ('2022-01-01', '2022-12-31'),
        '2023': ('2023-01-01', '2023-12-31'),
        '2024': ('2024-01-01', '2024-12-31'),
        '2025': ('2025-01-01', '2025-12-31'),
    }

    for period_name, (start, end) in periods.items():
        period_data = df.loc[start:end]
        if len(period_data) == 0:
            continue

        market_return = ((period_data['Close'].iloc[-1] / period_data['Close'].iloc[0]) - 1) * 100
        warnings_count = len(period_data[period_data['signal'] == 'warning'])
        entries_count = len(period_data[period_data['signal'] == 'entry'])
        bear_days = len(period_data[period_data['regime'] == 'bear'])

        print(f"\n{period_name}:")
        print(f"  市場報酬: {market_return:+.1f}%")
        print(f"  空頭警訊: {warnings_count} 次")
        print(f"  進場機會: {entries_count} 次")
        print(f"  空頭天數: {bear_days} / {len(period_data)} ({bear_days/len(period_data)*100:.0f}%)")

    return warnings, entries


def simulate_simple_strategy(df, warnings, entries):
    """
    模擬簡單策略：看訊號進出
    - Warning: 減倉 50%
    - Entry: 加倉
    """

    print(f"\n{'=' * 100}")
    print("簡單策略模擬：看訊號進出")
    print(f"{'=' * 100}")

    initial_capital = 1000000
    position_pct = 1.0  # 初始滿倉
    cash = initial_capital

    trades = []

    for idx, row in df.iterrows():
        if idx < df.index[200]:
            continue

        signal = row['signal']
        price = row['Close']

        if signal == 'warning':
            # 減倉 50%
            position_pct = 0.5
            action = '減倉 50%'
        elif signal == 'entry':
            # 加倉回滿
            position_pct = 1.0
            action = '加倉回滿'
        else:
            action = 'Hold'

        if action != 'Hold':
            trades.append({
                'date': idx.date(),
                'price': price,
                'action': action,
                'position': position_pct,
            })

    print(f"\n交易事件: {len(trades)} 次")

    # 計算績效
    if len(trades) > 0:
        print("\n詳細交易:")
        for trade in trades[:15]:  # 顯示前 15 筆
            print(f"{trade['date']}: {trade['action']} @ ${trade['price']:.2f}")

    # 模擬持倉比例的績效
    print(f"\n{'-' * 100}")
    print("持倉比例變化影響")
    print(f"{'-' * 100}")

    # 計算關鍵時期的虧損
    print("\n重要時期的保護效果:")

    # 2022 年大跌期間
    period_2022 = df.loc['2022-01-01':'2022-12-31']

    warnings_2022 = period_2022[period_2022['signal'] == 'warning']
    if len(warnings_2022) > 0:
        first_warning = warnings_2022.index[0]
        warning_price = warnings_2022.iloc[0]['Close']

        # 空頭期間最低點
        bear_period = df.loc[first_warning:'2022-12-31']
        lowest_price = bear_period['Close'].min()
        loss_if_full = (lowest_price / warning_price - 1) * 100

        print(f"\n2022 年 {first_warning.date()}: 發出警訊 @ ${warning_price:.2f}")
        print(f"隨後最低: ${lowest_price:.2f}")
        print(f"  - 如果滿倉: 虧損 {loss_if_full:.1f}%")
        print(f"  - 如果減倉 50%: 虧損 {loss_if_full * 0.5:.1f}%")
        print(f"  - 節省損失: {abs(loss_if_full * 0.5):.1f}%")


if __name__ == '__main__':
    # 加載數據
    df = pd.read_csv('data/006208_historical.csv', index_col='Date', parse_dates=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

    # 計算指標
    df = calculate_indicators(df)

    # 檢測市場制度
    df = detect_market_regime(df)

    # 分析結果
    warnings, entries = analyze_regimes(df)

    # 模擬策略
    simulate_simple_strategy(df, warnings, entries)

    print(f"\n{'=' * 100}\n")
