import pandas as pd
from orbital_yang.body_levels import Level
from orbital_yang.hypothesis_test import (
    TestParams, evaluate_levels, control_uniform, control_matched,
)


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


# L=100 下: epsilon_pct=0.005 -> eps=0.5, reaction_pct=0.05 -> react=5.0
_PARAMS = TestParams(epsilon_pct=0.005, window=4, reaction_pct=0.05)


def test_support_bounce_is_react_success():
    df = _df([100, 103, 100, 102, 106, 108])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    stats = evaluate_levels(df, [level], _PARAMS)
    assert stats.n_touch == 1
    assert stats.n_react == 1
    assert stats.react_rate == 1.0


def test_support_breakdown_is_not_react():
    df = _df([100, 101, 100, 96, 94, 93])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    stats = evaluate_levels(df, [level], _PARAMS)
    assert stats.n_touch == 1
    assert stats.n_react == 0
    assert stats.react_rate == 0.0


def test_control_uniform_is_reproducible():
    df = _df([100, 102, 101, 103, 99, 104, 100, 105])
    level = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    a = control_uniform(df, [level], _PARAMS, n_sets=10, seed=42)
    b = control_uniform(df, [level], _PARAMS, n_sets=10, seed=42)
    assert a.react_rate == b.react_rate


def test_control_matched_is_reproducible_and_same_side():
    # 真實支撐在收盤下方(open=95 < close=100); 方向匹配假關卡也應在下方且可重現
    df = _df([100, 102, 101, 103, 99, 104, 100, 105], opens=[95, 102, 101, 103, 99, 104, 100, 105])
    level = Level(idx=0, date=df["date"].iloc[0], price=95.0, kind="support")
    a = control_matched(df, [level], _PARAMS, n_sets=10, seed=7)
    b = control_matched(df, [level], _PARAMS, n_sets=10, seed=7)
    assert a.react_rate == b.react_rate
    assert a.n_levels == 10
