"""假設檢定: 大實體K關卡的支撐/壓力反應率, 對照隨機價位。"""
from dataclasses import dataclass
import numpy as np

from .body_levels import Level


@dataclass
class TestParams:
    epsilon: float    # 碰觸容忍(點)
    window: int       # 反應觀察窗(根)
    reaction: float   # 視為反彈/受阻所需幅度(點)


@dataclass
class Stats:
    n_levels: int
    n_touch: int
    n_react: int
    react_rate: float       # n_react / n_touch (touch=0 時為 0.0)
    avg_reaction: float     # 反彈成功者平均幅度


def _react_one(o, c, lo_body, hi_body, level: Level, params: TestParams):
    """回傳 (touched: bool, reacted: bool, magnitude: float)。"""
    L = level.price
    n = len(c)
    for j in range(level.idx + 1, n):
        if lo_body[j] <= L + params.epsilon and hi_body[j] >= L - params.epsilon:
            end = min(n, j + 1 + params.window)
            if level.kind == "support":
                for t in range(j + 1, end):
                    if c[t] <= L - params.epsilon:
                        return (True, False, 0.0)
                    if c[t] - L >= params.reaction:
                        return (True, True, c[t] - L)
            else:  # resistance
                for t in range(j + 1, end):
                    if c[t] >= L + params.epsilon:
                        return (True, False, 0.0)
                    if L - c[t] >= params.reaction:
                        return (True, True, L - c[t])
            return (True, False, 0.0)
    return (False, False, 0.0)


def evaluate_levels(df, levels, params: TestParams) -> Stats:
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    lo_body = np.minimum(o, c)
    hi_body = np.maximum(o, c)

    n_touch = n_react = 0
    mags = []
    for lv in levels:
        touched, reacted, mag = _react_one(o, c, lo_body, hi_body, lv, params)
        if touched:
            n_touch += 1
        if reacted:
            n_react += 1
            mags.append(mag)
    rate = (n_react / n_touch) if n_touch else 0.0
    avg = float(np.mean(mags)) if mags else 0.0
    return Stats(len(levels), n_touch, n_react, rate, avg)


def random_control(df, levels, params: TestParams, n_sets: int, seed: int) -> Stats:
    """生成與真關卡同數量/同 kind 分佈、但價位隨機的假關卡, 聚合 n_sets 次結果。

    隨機價位於 [收盤最小, 收盤最大] 均勻抽樣; 形成索引取真關卡的索引(對齊)。
    """
    rng = np.random.default_rng(seed)
    c = df["close"].to_numpy(float)
    lo, hi = float(c.min()), float(c.max())

    tot_touch = tot_react = 0
    mags = []
    for _ in range(n_sets):
        fake = []
        for lv in levels:
            price = float(rng.uniform(lo, hi))
            fake.append(Level(lv.idx, lv.date, price, lv.kind))
        s = evaluate_levels(df, fake, params)
        tot_touch += s.n_touch
        tot_react += s.n_react
        if s.avg_reaction:
            mags.append(s.avg_reaction)
    rate = (tot_react / tot_touch) if tot_touch else 0.0
    avg = float(np.mean(mags)) if mags else 0.0
    return Stats(len(levels) * n_sets, tot_touch, tot_react, rate, avg)
