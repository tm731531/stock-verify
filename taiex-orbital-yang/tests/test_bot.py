import pandas as pd
from orbital_yang.bot import trade_card, _prior_regime
from orbital_yang.orb import ORBParams


def _daily(closes, start="2026-01-01"):
    return pd.DataFrame({"date": pd.date_range(start, periods=len(closes), freq="D"),
                         "close": closes})


def _min1(date, rows):
    ts = [pd.Timestamp(f"{date} {r[0]}") for r in rows]
    return pd.DataFrame({"ts": ts, "Open": [r[1] for r in rows], "High": [r[2] for r in rows],
                         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
                         "Volume": [1] * len(rows)})


def test_prior_regime_uses_before_date():
    daily = _daily(list(range(1, 80)))                 # 單調上升 -> 多格局
    r = _prior_regime(daily, "2026-03-20", fast=20, slow=60)
    assert r == 1


def test_trade_card_long_in_bull_regime():
    daily = _daily(list(range(1, 80)))                 # 多格局
    d = "2026-03-20"
    m = _min1(d, [("08:46", 100, 102, 98, 100), ("08:47", 100, 103, 100, 103),
                  ("08:48", 103, 160, 103, 155)])      # 收破基準高 -> 做多 -> 停利
    card = trade_card(daily, m, d, ORBParams(take_profit=50.0))
    assert card.regime == 1
    assert card.has_trade and card.direction == "long" and card.reason == "tp"
    assert card.tp == 153.0 and card.stop == 98.0


def test_no_trade_when_counter_trend():
    daily = _daily(list(range(80, 1, -1)))             # 空格局
    d = "2026-03-20"
    m = _min1(d, [("08:46", 100, 102, 98, 100), ("08:47", 100, 103, 100, 103),
                  ("08:48", 103, 160, 103, 155)])      # 多突破, 但空格局 -> 不做
    card = trade_card(daily, m, d, ORBParams(take_profit=50.0))
    assert card.regime == -1
    assert card.has_trade is False
