import pandas as pd
from orbital_yang.levels_lo import prior_levels, run_lo, LOParams


def _daily(rows):
    # rows: list of (date, open, high, low, close)
    return pd.DataFrame({"date": pd.to_datetime([r[0] for r in rows]),
                         "open": [r[1] for r in rows], "high": [r[2] for r in rows],
                         "low": [r[3] for r in rows], "close": [r[4] for r in rows]})


def _min1(date, rows):
    ts = [pd.Timestamp(f"{date} {r[0]}") for r in rows]
    return pd.DataFrame({"ts": ts, "Open": [r[1] for r in rows], "High": [r[2] for r in rows],
                         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows], "Volume": [1]*len(rows)})


def _bull_daily(n=80):
    """n business days of rising prices so MA20 > MA60 (bull regime) by day 65+."""
    dates = pd.date_range("2026-01-02", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    return _daily([(dates[d], 100+d, 110+d, 90+d, 105+d) for d in range(n)])


def test_prior_levels():
    daily = _daily([("2026-03-18", 100, 110, 90, 105), ("2026-03-19", 106, 112, 104, 108)])
    lv = prior_levels(daily, "2026-03-19")
    assert ("昨低", 90.0) in lv and ("昨高", 110.0) in lv


def test_long_retest_fill_tp():
    # 多格局: 80 business days so MA60 is defined by day 65+; use 2026-04-03
    # Prior day 2026-04-02: d=65 -> open=164, high=174, low=154, close=169
    # Today open=200 → all 4 levels below 200 → nearest = 174 (昨高)
    daily = _bull_daily(80)
    d = "2026-04-03"
    m = _min1(d, [("08:46", 200, 201, 199, 200),   # open bar, op=200
                  ("08:47", 199, 200, 173, 174),    # Low=173 ≤ 174 → fill at 174 (昨高)
                  ("08:48", 174, 225, 174, 224)])   # High=225 ≥ 174+50=224 → TP
    tr = run_lo(daily, m, LOParams(take_profit=50.0, stop=50.0))
    assert len(tr) == 1
    assert tr[0].direction == "long" and tr[0].reason == "tp"
    assert tr[0].line == 174.0 and tr[0].pnl == 50.0


def test_long_retest_stop():
    # Same setup: fill at 174, then stop at 174-50=124
    daily = _bull_daily(80)
    d = "2026-04-03"
    m = _min1(d, [("08:46", 200, 201, 199, 200),   # open bar
                  ("08:47", 199, 200, 173, 174),    # Low=173 ≤ 174 → fill
                  ("08:48", 174, 175, 123, 124)])   # Low=123 ≤ 174-50=124 → stop
    tr = run_lo(daily, m, LOParams(take_profit=50.0, stop=50.0))
    assert tr[0].reason == "stop" and tr[0].pnl == -50.0
