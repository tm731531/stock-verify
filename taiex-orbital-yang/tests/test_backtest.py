import pandas as pd
from orbital_yang.body_levels import Level
from orbital_yang.backtest import BacktestParams, Trade, run_backtest, summarize


def _df(closes, opens):
    n = len(closes)
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


_P = BacktestParams(breakout_pct=0.001, stop_buffer_pct=0.003, target_mult=1.0, max_hold=10)


def test_long_breakout_hits_target_is_win():
    # 黑頂壓力=100 (idx0 大黑K, 實體15); 收盤 99->102 過破做多; target=102+15=117
    closes = [99, 102, 106, 112, 118]
    opens = [84, 102, 106, 112, 118]   # idx0 body = |99-84| = 15
    df = _df(closes, opens)
    lv = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="resistance")
    trades = run_backtest(df, [lv], _P)
    assert len(trades) == 1
    assert trades[0].direction == "long"
    assert trades[0].reason == "target"
    assert trades[0].pnl > 0


def test_long_breakout_hits_stop_is_loss():
    # 同上進場 102, stop=100*0.997=99.7; 收盤掉到 98 -> 停損
    closes = [99, 102, 98, 98, 98]
    opens = [84, 102, 98, 98, 98]
    df = _df(closes, opens)
    lv = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="resistance")
    trades = run_backtest(df, [lv], _P)
    assert len(trades) == 1
    assert trades[0].reason == "stop"
    assert trades[0].pnl < 0


def test_short_breakdown_enters_short():
    # 紅底支撐=100 (idx0 大紅K 實體15); 收盤 101->98 破 -> 做空
    closes = [101, 98, 95, 90, 85]
    opens = [86, 98, 95, 90, 85]       # idx0 body = |101-86| = 15
    df = _df(closes, opens)
    lv = Level(idx=0, date=df["date"].iloc[0], price=100.0, kind="support")
    trades = run_backtest(df, [lv], _P)
    assert len(trades) == 1
    assert trades[0].direction == "short"
    assert trades[0].pnl > 0


def test_summarize_math():
    trades = [
        Trade(1, 2, "long", 100, 120, 20.0, "target"),
        Trade(3, 4, "long", 100, 90, -10.0, "stop"),
    ]
    perf = summarize(trades)
    assert perf.n_trades == 2
    assert perf.n_win == 1
    assert perf.win_rate == 0.5
    assert perf.avg_win == 20.0
    assert perf.avg_loss == -10.0
    assert perf.payoff == 2.0
    assert perf.expectancy == 5.0
    assert perf.total_pnl == 10.0
