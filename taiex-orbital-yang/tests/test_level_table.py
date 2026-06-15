import pandas as pd
from orbital_yang.level_table import rsi, detect_body_gaps, build_table


def _df(rows):
    dates = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame({
        "date": dates,
        "open": [r[0] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "volume": [1] * len(rows),
    })


def test_rsi_all_up_is_100():
    assert rsi([1, 2, 3, 4, 5], 3) == 100.0


def test_detect_body_gap_up():
    # day1 body [100,110]; day2 body [120,130] -> 不重疊, 向上實體缺口
    df = _df([(100, 115, 95, 110), (120, 135, 118, 130)])
    gaps = detect_body_gaps(df)
    assert len(gaps) == 1
    assert gaps[0]["direction"] == "up"


def test_detect_body_gap_none_when_overlap():
    # day2 body [105,115] 與 day1 [100,110] 重疊 -> 無缺口 (即使有長影線)
    df = _df([(100, 200, 50, 110), (105, 250, 10, 115)])
    assert detect_body_gaps(df) == []


def test_build_table_has_derived_and_sorted():
    rows = [(100, 110, 90, 105), (106, 116, 104, 112), (108, 120, 100, 118)]
    df = _df(rows)
    table = build_table(df, window=3)
    # 由高到低排序
    prices = [r.price for r in table]
    assert prices == sorted(prices, reverse=True)
    # 9折/8折-最高價 = max(high)=120 的 0.9/0.8
    labels = {r.label: r.price for r in table}
    assert abs(labels["9折-最高價"] - 120 * 0.9) < 1e-6
    assert abs(labels["8折-最高價"] - 120 * 0.8) < 1e-6
    # 當前(最後一天)那幾排 is_current
    assert any(r.is_current for r in table)
    # 滿 = (price - 當前收118)/25
    nine = next(r for r in table if r.label == "9折-最高價")
    assert abs(nine.man - (120 * 0.9 - 118) / 25) < 1e-6
