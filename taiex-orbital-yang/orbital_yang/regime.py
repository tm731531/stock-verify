"""大小流氓(月季線 MA20/MA60)轉勢偵測。

只在『剛轉勢後 window 日內、且方向=轉勢方向』允許交易。
"""
import numpy as np
import pandas as pd


def alignment_sign(daily_df, fast: int = 20, slow: int = 60):
    """每日 MA_fast vs MA_slow: +1(快>慢) / -1(快<慢) / 0(未定義或相等)。"""
    c = daily_df["close"].to_numpy(float)
    maf = pd.Series(c).rolling(fast).mean().to_numpy()
    mas = pd.Series(c).rolling(slow).mean().to_numpy()
    sign = np.zeros(len(c), dtype=int)
    sign[maf > mas] = 1
    sign[maf < mas] = -1
    sign[np.isnan(maf) | np.isnan(mas)] = 0
    return sign


def fresh_turn_direction(daily_df, fast: int = 20, slow: int = 60, window: int = 20) -> dict:
    """回傳 {date_str 'YYYY-MM-DD': +1/-1}: 該日落在某次轉勢後 window 日內, 值=轉勢方向。

    轉勢日 = sign 由前一日變成新的非零方向。後續轉勢會覆寫(最新轉勢為準)。
    """
    sign = alignment_sign(daily_df, fast, slow)
    dates = pd.to_datetime(daily_df["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    allowed = {}
    for i in range(1, len(sign)):
        if sign[i] != 0 and sign[i] != sign[i - 1]:
            for j in range(i, min(len(sign), i + window + 1)):
                allowed[str(dates[j])] = int(sign[i])
    return allowed
