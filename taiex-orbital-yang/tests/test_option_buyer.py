import pandas as pd
from orbital_yang.backtest import Trade
from orbital_yang.option_buyer import (
    bs_price, solve_strike, OptionParams, simulate_option_trades, summarize_options,
)


def test_bs_atm_known_value():
    # S=K=100, T=1, sigma=0.2, r=0 -> ~7.97
    p = bs_price(100, 100, 1.0, 0.2, "call")
    assert abs(p - 7.97) < 0.05


def test_bs_expiry_intrinsic():
    assert bs_price(130, 100, 0.0, 0.2, "call") == 30.0
    assert bs_price(130, 100, 0.0, 0.2, "put") == 0.0


def test_solve_strike_hits_target_premium():
    S, T, sigma = 20000.0, 5 / 252, 0.2
    K = solve_strike(S, T, sigma, "call", 30.0)
    assert K > S                                  # call -> 價外在上方
    assert abs(bs_price(S, K, T, sigma, "call") - 30.0) < 1.0


def _df(closes):
    n = len(closes)
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({"date": dates, "open": closes, "high": closes,
                         "low": closes, "close": closes, "volume": [1] * n})


def test_long_call_big_move_wins():
    df = _df([20000, 20100, 20400, 20400])
    tr = Trade(0, 2, "long", 20000, 20400, 400, "target")
    params = OptionParams(iv=0.2, expiry_days=3, target_premium=30.0)
    ots = simulate_option_trades(df, [tr], params)
    assert len(ots) == 1
    assert ots[0].kind == "call"
    assert ots[0].pnl > 0
    assert ots[0].mult > 1.0


def test_long_call_flat_loses():
    df = _df([20000, 19990, 19980, 19980])
    tr = Trade(0, 2, "long", 20000, 19980, -20, "stop")
    params = OptionParams(iv=0.2, expiry_days=3, target_premium=30.0)
    ots = simulate_option_trades(df, [tr], params)
    assert ots[0].pnl < 0


def test_summarize_multiples():
    df = _df([20000, 20500, 20800, 20800])
    trades = [
        Trade(0, 2, "long", 20000, 20800, 800, "target"),
        Trade(0, 2, "short", 20000, 20800, -800, "stop"),  # put with index up -> 歸零
    ]
    params = OptionParams(iv=0.2, expiry_days=3, target_premium=30.0)
    perf = summarize_options(simulate_option_trades(df, trades, params))
    assert perf.n_trades == 2
    assert 0.0 <= perf.rate_2x <= 1.0
    assert 0.0 <= perf.worthless_rate <= 1.0


def test_costs_reduce_pnl():
    import pandas as pd
    from orbital_yang.backtest import Trade
    df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=4, freq="D"),
                       "open": [20000, 20300, 20600, 20600], "high": [20000, 20300, 20600, 20600],
                       "low": [20000, 20300, 20600, 20600], "close": [20000, 20300, 20600, 20600],
                       "volume": [1, 1, 1, 1]})
    tr = Trade(0, 2, "long", 20000, 20600, 600, "target")
    gross = simulate_option_trades(df, [tr], OptionParams(0.2, 3, 30.0))[0]
    net = simulate_option_trades(df, [tr], OptionParams(0.2, 3, 30.0, half_spread_pts=1.0, commission_ntd=20.0))[0]
    assert net.pnl < gross.pnl                       # 成本讓淨損益變低
    # 一個贏單的成本 = 來回價差(2) + 來回手續費(2*20/50=0.8) = 2.8 點
    assert abs((gross.pnl - net.pnl) - 2.8) < 1e-6
