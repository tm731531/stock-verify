import pandas as pd
from orbital_yang.orb import run_orb, summarize_orb, ORBParams


def _bars(date, rows):
    """rows: list of (hhmm, open, high, low, close)。"""
    ts = [pd.Timestamp(f"{date} {r[0]}") for r in rows]
    return pd.DataFrame({
        "ts": ts,
        "Open": [r[1] for r in rows], "High": [r[2] for r in rows],
        "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
        "Volume": [1] * len(rows),
    })


_P = ORBParams(take_profit=50.0)


def test_long_breakout_hits_tp():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),     # 基準: high102 low98
        ("08:46", 100, 103, 100, 103),    # 收103>102 -> 做多@103, tp=153, stop=98
        ("08:47", 103, 160, 103, 155),    # high160>=153 -> 停利
    ])
    tr = run_orb(df, _P)
    assert len(tr) == 1
    assert tr[0].direction == "long" and tr[0].reason == "tp"
    assert tr[0].pnl == 50.0


def test_long_breakout_hits_stop():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),
        ("08:46", 100, 103, 100, 103),    # 做多@103, stop=98
        ("08:47", 103, 103, 95, 96),      # low95<=98 -> 停損@98
    ])
    tr = run_orb(df, _P)
    assert tr[0].reason == "stop" and tr[0].pnl == -5.0


def test_short_breakout_hits_tp():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),
        ("08:46", 100, 100, 96, 97),      # 收97<98 -> 做空@97, tp=47, stop=102
        ("08:47", 97, 97, 45, 46),        # low46<=47 -> 停利
    ])
    tr = run_orb(df, _P)
    assert tr[0].direction == "short" and tr[0].reason == "tp" and tr[0].pnl == 50.0


def test_no_signal_in_range():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),
        ("08:46", 100, 101, 99, 100),
        ("08:47", 100, 101, 99, 100),
    ])
    assert run_orb(df, _P) == []


def test_eod_exit():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),
        ("08:46", 100, 103, 100, 103),    # 做多@103
        ("08:47", 103, 104, 102, 103),    # 沒到 tp153/stop98
        ("13:45", 103, 104, 102, 104),    # 收盤平倉@104
    ])
    tr = run_orb(df, _P)
    assert tr[0].reason == "eod" and tr[0].pnl == 1.0


def test_summarize():
    df = _bars("2026-06-10", [
        ("08:45", 100, 102, 98, 100),
        ("08:46", 100, 103, 100, 103),
        ("08:47", 103, 160, 103, 155),
    ])
    perf = summarize_orb(run_orb(df, _P))
    assert perf.n == 1 and perf.n_tp == 1 and perf.expectancy == 50.0
