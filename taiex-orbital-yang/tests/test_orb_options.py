import pandas as pd
from orbital_yang.orb_options import (
    apply_futures_cost, option_ohlc, buyer_pnl, summarize_buyer,
)


def test_apply_futures_cost():
    # 毛 +50, 滑價1/邊, 手續費40/邊(/200=0.2pt) -> 來回 2*(1+0.2)=2.4 -> 47.6
    assert abs(apply_futures_cost(50.0, 1.0, 40.0, 200.0) - 47.6) < 1e-9


def test_option_ohlc_found():
    ch = pd.DataFrame([
        {"contract_date": "202606F2", "strike_price": 44500, "call_put": "call",
         "open": 30, "max": 95, "min": 12, "close": 80, "trading_session": "position"},
    ])
    o = option_ohlc(ch, "202606F2", 44500, "call")
    assert o["open"] == 30 and o["high"] == 95 and o["close"] == 80


def test_buyer_pnl_costs():
    # 進30 出80, 半價差1, 手續費20(/50=0.4) -> 付30+1.4=31.4, 收80-1.4=78.6 -> +47.2
    assert abs(buyer_pnl(30.0, 80.0, 1.0, 20.0, 50.0) - 47.2) < 1e-9
    # 歸零: 出0 -> 收 max(0,-1.4)=0 -> -31.4
    assert abs(buyer_pnl(30.0, 0.0, 1.0, 20.0, 50.0) - (-31.4)) < 1e-9


def test_summarize_buyer():
    rows = [{"entry": 30, "base_pnl": -10, "best_pnl": 60},
            {"entry": 30, "base_pnl": 50, "best_pnl": 90}]
    s = summarize_buyer(rows)
    assert s.n == 2
    assert abs(s.base_expectancy - 20.0) < 1e-9
    assert abs(s.best_expectancy - 75.0) < 1e-9
    assert s.base_winrate == 0.5
