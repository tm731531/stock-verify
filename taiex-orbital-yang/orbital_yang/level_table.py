"""軌道鞅「策略關卡表」生成器。

把日線 OHLC 攤成價格天梯 (每天開高低收 + 衍生關卡), 由高到低排序, 標出:
- 9折/8折-最高價 (位移退檔: 視窗最高 × 0.9 / 0.8)
- 各關卡距當前收盤的『滿』數 (1滿 = 25 點)
- 實體缺口 (詭道: 今日實體與昨日實體不重疊的跳空; 上方↑/下方↓)
- 當前 K 棒 OHLC (highlighted) + RSI3
待確認 (老師課程內行話, 未實作): 對稱缺口、小妹、X 記號。
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

MAN = 25.0  # 1滿 = 台指期 25 點


@dataclass
class LevelRow:
    label: str        # 'MM-DD高' / '9折-最高價' / '台指期-收' ...
    price: float
    man: float        # 距當前收盤幾滿 (signed, 正=在上方)
    note: str         # 缺口 / RSI 等註記
    is_current: bool  # 是否為當前 K 棒那幾排


def rsi(closes, period: int = 3) -> float:
    """簡化 RSI (period 期, 簡單均值), 回傳最後一個值。資料不足回 nan。"""
    c = np.asarray(closes, float)
    if len(c) <= period:
        return float("nan")
    d = np.diff(c)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = up[-period:].mean()
    ad = dn[-period:].mean()
    if ad == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + au / ad)


def detect_body_gaps(df) -> list:
    """實體缺口: 今日實體 [min(o,c),max(o,c)] 與昨日實體不重疊。

    回傳 list of dict{date:'MM-DD', direction:'up'/'down', low, high}。
    """
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    dates = df["date"].dt.strftime("%m-%d").to_numpy()
    lob = np.minimum(o, c)
    hib = np.maximum(o, c)
    gaps = []
    for i in range(1, len(df)):
        if lob[i] > hib[i - 1]:
            gaps.append({"date": dates[i], "direction": "up",
                         "low": hib[i - 1], "high": lob[i]})
        elif hib[i] < lob[i - 1]:
            gaps.append({"date": dates[i], "direction": "down",
                         "low": hib[i], "high": lob[i - 1]})
    return gaps


def build_table(df, window: int = 60, man: float = MAN) -> list:
    """建關卡天梯。df 需 date/open/high/low/close (date 為 datetime)。取最後 window 天。"""
    sub = df.iloc[-window:].reset_index(drop=True)
    cur = sub.iloc[-1]
    cur_close = float(cur["close"])
    rows = []

    # 歷史每天的 開高低收 (不含最後一天, 最後一天當『當前』)
    for _, r in sub.iloc[:-1].iterrows():
        d = r["date"].strftime("%m-%d")
        for kind, col in [("開", "open"), ("高", "high"), ("低", "low"), ("收", "close")]:
            p = float(r[col])
            rows.append(LevelRow(f"{d}{kind}", p, (p - cur_close) / man, "", False))

    # 衍生關卡: 9折 / 8折 - 最高價
    hi = float(sub["high"].max())
    rows.append(LevelRow("9折-最高價", hi * 0.9, (hi * 0.9 - cur_close) / man, "位移退檔", False))
    rows.append(LevelRow("8折-最高價", hi * 0.8, (hi * 0.8 - cur_close) / man, "位移退檔", False))

    # 當前 K 棒 OHLC (highlighted), RSI3 標在收盤排
    r3 = rsi(sub["close"], 3)
    for kind, col in [("開", "open"), ("高", "high"), ("低", "low"), ("收", "close")]:
        p = float(cur[col])
        note = f"RSI3={r3:.0f}" if kind == "收" else ""
        rows.append(LevelRow(f"台指期-{kind}", p, (p - cur_close) / man, note, True))

    # 實體缺口: 貼到中價最近的關卡 note
    for g in detect_body_gaps(sub):
        arrow = "↑" if g["direction"] == "up" else "↓"
        mid = 0.5 * (g["low"] + g["high"])
        nearest = min(rows, key=lambda x: abs(x.price - mid))
        nearest.note = (nearest.note + f" {arrow}{g['date']}實體缺口").strip()

    rows.sort(key=lambda x: x.price, reverse=True)
    return rows


def to_csv_rows(rows: list) -> list:
    """轉成可寫 CSV 的 list[list]: [關卡, 價格, 滿, 註記, 當前]。"""
    out = [["關卡", "價格", "滿(距現價)", "註記", "當前"]]
    for r in rows:
        out.append([r.label, f"{r.price:.0f}", f"{r.man:+.1f}", r.note,
                    "★" if r.is_current else ""])
    return out
