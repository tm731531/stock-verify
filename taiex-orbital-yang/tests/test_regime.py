import pandas as pd
from orbital_yang.regime import alignment_sign, fresh_turn_direction


def _daily(closes):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(closes), freq="D"),
        "close": closes,
    })


def test_alignment_sign_rising():
    df = _daily([10, 10, 10, 11, 12, 13, 14, 15])
    s = alignment_sign(df, fast=2, slow=3)
    assert s[0] == 0 and s[1] == 0           # MA 未定義
    assert s[-1] == 1                          # 上升 -> 快線>慢線


def test_fresh_turn_marks_window_in_direction():
    # 上升序列: idx3 起 MA2>MA3 -> 轉多
    df = _daily([10, 10, 10, 11, 12, 13, 14, 15, 16, 17])
    allowed = fresh_turn_direction(df, fast=2, slow=3, window=2)
    keys = sorted(allowed.keys())
    # 轉勢日(2026-01-04, idx3)起後 2 日都標 +1
    assert allowed["2026-01-04"] == 1
    assert allowed["2026-01-05"] == 1
    assert allowed["2026-01-06"] == 1
    # 轉勢前(idx0-2)不在允許表
    assert "2026-01-01" not in allowed
