"""詭道原則: 只算實體 open->close, 丟棄 high/low。

大實體K -> 實體邊緣作為支撐/壓力關卡:
  大紅K(收>開) -> 紅底 = 開盤價 (support)
  大黑K(收<開) -> 黑頂 = 開盤價 (resistance)
"""
from dataclasses import dataclass
import pandas as pd


@dataclass
class Level:
    idx: int        # 形成關卡的 K 棒索引
    date: object    # 該 K 棒日期
    price: float    # 關卡價(大實體K 的開盤價)
    kind: str       # 'support' (紅底) 或 'resistance' (黑頂)


def body(df: pd.DataFrame) -> pd.Series:
    """實體大小 = |close - open|(不含影線)。"""
    return (df["close"] - df["open"]).abs()


def detect_big_bodies(df: pd.DataFrame, n: int, k: float) -> pd.Series:
    """布林 Series: body[i] > 前 n 根 body 的中位數 × k。

    前 n 根不足者為 False(rolling 產生 NaN, 比較後為 False)。
    """
    b = body(df)
    med = b.shift(1).rolling(n).median()
    return (b > med * k).fillna(False)


def detect_levels(df: pd.DataFrame, n: int, k: float) -> list:
    """回傳所有大實體K 形成的紅底/黑頂關卡。"""
    big = detect_big_bodies(df, n, k)
    levels = []
    for i in range(len(df)):
        if not bool(big.iloc[i]):
            continue
        o = float(df["open"].iloc[i])
        c = float(df["close"].iloc[i])
        if c > o:
            levels.append(Level(i, df["date"].iloc[i], o, "support"))
        elif c < o:
            levels.append(Level(i, df["date"].iloc[i], o, "resistance"))
    return levels
