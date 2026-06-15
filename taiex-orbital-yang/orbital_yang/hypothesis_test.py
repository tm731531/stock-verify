"""假設檢定: 大實體K關卡的支撐/壓力反應率, 對照(均勻 + 方向匹配)隨機價位。

詭道原則: 只看實體 open/close。門檻改用百分比(相對關卡價), 避免跨價格區間偏誤。
"""
from dataclasses import dataclass
import numpy as np

from .body_levels import Level


@dataclass
class TestParams:
    epsilon_pct: float    # 碰觸容忍(關卡價的比例, e.g. 0.001 = 0.1%)
    window: int           # 反應觀察窗(根)
    reaction_pct: float   # 視為反彈/受阻所需幅度(關卡價的比例, e.g. 0.005 = 0.5%)


@dataclass
class Stats:
    n_levels: int
    n_touch: int
    n_react: int
    react_rate: float
    avg_reaction: float   # 反彈成功者平均幅度(點)


def _react_one(o, c, lo_body, hi_body, level: Level, params: TestParams):
    """回傳 (touched, reacted, magnitude)。門檻相對關卡價 L 以百分比換算。"""
    L = level.price
    eps = L * params.epsilon_pct
    react = L * params.reaction_pct
    n = len(c)
    for j in range(level.idx + 1, n):
        if lo_body[j] <= L + eps and hi_body[j] >= L - eps:
            end = min(n, j + 1 + params.window)
            if level.kind == "support":
                for t in range(j + 1, end):
                    if c[t] <= L - eps:
                        return (True, False, 0.0)
                    if c[t] - L >= react:
                        return (True, True, c[t] - L)
            else:  # resistance
                for t in range(j + 1, end):
                    if c[t] >= L + eps:
                        return (True, False, 0.0)
                    if L - c[t] >= react:
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


def _aggregate(df, make_fake, levels, params, n_sets, seed) -> Stats:
    """共用: 用 make_fake(rng, level) 生 n_sets 組假關卡, 聚合 pooled 反應率。"""
    rng = np.random.default_rng(seed)
    tot_touch = tot_react = 0
    mags = []
    for _ in range(n_sets):
        fake = [make_fake(rng, lv) for lv in levels]
        s = evaluate_levels(df, fake, params)
        tot_touch += s.n_touch
        tot_react += s.n_react
        if s.n_react:
            mags.append(s.avg_reaction)
    rate = (tot_react / tot_touch) if tot_touch else 0.0
    avg = float(np.mean(mags)) if mags else 0.0
    return Stats(len(levels) * n_sets, tot_touch, tot_react, rate, avg)


def control_uniform(df, levels, params: TestParams, n_sets: int, seed: int) -> Stats:
    """舊對照(保留作對比): [收盤min, 收盤max] 均勻抽價, 同 idx/kind。"""
    c = df["close"].to_numpy(float)
    lo, hi = float(c.min()), float(c.max())

    def make_fake(rng, lv):
        return Level(lv.idx, lv.date, float(rng.uniform(lo, hi)), lv.kind)

    return _aggregate(df, make_fake, levels, params, n_sets, seed)


def control_matched(df, levels, params: TestParams, n_sets: int, seed: int) -> Stats:
    """方向匹配對照: 假關卡放在同根K收盤的『正確方向』偏移帶內。

    支撐 -> 收盤下方; 壓力 -> 收盤上方。偏移量自真實關卡(關卡價與同根收盤的距離)
    取中位數 m, 每個假關卡隨機抽 [0, 2m]。如此假關卡與真關卡同側、同量級,
    只差『不是大實體K選出來的』—— 隔離出『大實體選擇』本身有沒有加值。
    """
    c = df["close"].to_numpy(float)
    if not levels:
        return Stats(0, 0, 0, 0.0, 0.0)
    offsets = [abs(c[lv.idx] - lv.price) for lv in levels]
    m = float(np.median(offsets)) or 1.0  # 全為 0 時退回 1.0 避免退化

    def make_fake(rng, lv):
        off = float(rng.uniform(0.0, 2.0 * m))
        price = c[lv.idx] - off if lv.kind == "support" else c[lv.idx] + off
        return Level(lv.idx, lv.date, price, lv.kind)

    return _aggregate(df, make_fake, levels, params, n_sets, seed)
