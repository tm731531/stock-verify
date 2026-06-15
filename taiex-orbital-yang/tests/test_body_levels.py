import pandas as pd
from orbital_yang.body_levels import body, detect_big_bodies, detect_levels


def _df(rows):
    """rows: list of (open, high, low, close)。日期自動產生,volume 固定。"""
    dates = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1000] * len(rows),
        }
    )


def test_body_ignores_wicks():
    df = _df([(100, 999, 1, 110)])  # 巨大上下影線, 實體=10
    assert body(df).iloc[0] == 10


def test_kuidao_open_low_close_flat_counts_as_big_red():
    """詭道測試1: 開低收平盤 = 大實體紅K, 必須被判為大紅K -> support。"""
    rows = [(100, 101, 99, 100.5)] * 20          # 20 根小實體 (body=0.5)
    rows.append((90, 100.2, 89, 100))            # 開低(90)收平盤(100), 大實體紅K body=10
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 1
    assert levels[0].kind == "support"
    assert levels[0].price == 90      # 紅底 = 大紅K開盤價


def test_kuidao_long_doji_wick_not_big():
    """詭道測試2: 長十字影線(實體極小)不可被判為大K。"""
    rows = [(100, 101, 99, 100.5)] * 20          # body=0.5
    rows.append((100, 200, 10, 100.3))           # 影線巨大但實體=0.3
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 0


def test_big_black_makes_resistance():
    rows = [(100, 101, 99, 100.5)] * 20
    rows.append((110, 111, 99, 100))             # 大黑K body=10, 開盤110
    df = _df(rows)
    levels = detect_levels(df, n=20, k=2.0)
    assert len(levels) == 1
    assert levels[0].kind == "resistance"
    assert levels[0].price == 110     # 黑頂 = 大黑K開盤價
