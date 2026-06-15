import pandas as pd
from orbital_yang.body_levels import Level
from orbital_yang.hypothesis_test import TestParams, evaluate_levels, random_control


def _df(closes, opens=None):
    n = len(closes)
    opens = opens or closes
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1000] * n,
        }
    )


def test_support_bounce_is_react_success():
    # 關卡 L=100 形成於 idx0; 之後跌到觸碰 100 再彈到 >=105
    df = _df([100, 103, 100, 102, 106, 108])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    stats = evaluate_levels(df, [level], params)
    assert stats.n_touch == 1
    assert stats.n_react == 1
    assert stats.react_rate == 1.0


def test_support_breakdown_is_not_react():
    # 觸碰 100 後直接跌破到 94(< L-eps), 不算反彈成功
    df = _df([100, 101, 100, 96, 94, 93])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    stats = evaluate_levels(df, [level], params)
    assert stats.n_touch == 1
    assert stats.n_react == 0
    assert stats.react_rate == 0.0


def test_random_control_is_reproducible():
    df = _df([100, 102, 101, 103, 99, 104, 100, 105])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    params = TestParams(epsilon=0.5, window=4, reaction=5.0)
    a = random_control(df, [level], params, n_sets=10, seed=42)
    b = random_control(df, [level], params, n_sets=10, seed=42)
    assert a.react_rate == b.react_rate     # 固定種子可重現
