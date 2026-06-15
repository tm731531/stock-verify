import pandas as pd
from orbital_yang.backtest import Trade
from orbital_yang.analyze import (
    drawdown_series, find_selloffs, down_regime_mask,
    trades_in_episodes, split_long_short, equity_max_drawdown,
)


def test_drawdown_series_basic():
    dd = drawdown_series([100, 110, 99, 120])
    assert dd[0] == 0.0
    assert dd[1] == 0.0          # new high
    assert round(dd[2], 4) == round(99 / 110 - 1, 4)
    assert dd[3] == 0.0          # new high again


def test_find_selloffs_detects_drop():
    # 峰 120 (idx2) -> 谷 96 (idx4) = -20%, 再創新高
    closes = [100, 110, 120, 108, 96, 130]
    eps = find_selloffs(closes, min_drop=0.05)
    assert len(eps) == 1
    peak_idx, trough_idx, drop = eps[0]
    assert peak_idx == 2
    assert trough_idx == 4
    assert drop < -0.15


def test_find_selloffs_ignores_small_dip():
    closes = [100, 101, 100.5, 102, 103]   # 最大回撤 < 5%
    assert find_selloffs(closes, min_drop=0.05) == []


def test_down_regime_mask():
    # 前 2 根報酬: idx2 = 98/100-1 <0 True; idx3 = 105/102-1 >0 False
    df = pd.DataFrame({"close": [100, 102, 98, 105, 96]})
    mask = down_regime_mask(df, lookback=2)
    assert mask[0] == False and mask[1] == False
    assert mask[2] == True
    assert mask[3] == False
    assert mask[4] == True       # 96/98-1 < 0


def test_trades_in_episodes():
    eps = [(2, 4, -0.2)]
    trades = [
        Trade(1, 2, "long", 100, 110, 10, "target"),   # entry_idx 1 -> 外
        Trade(3, 5, "short", 110, 100, 10, "target"),  # entry_idx 3 -> 內
    ]
    inside = trades_in_episodes(trades, eps)
    assert len(inside) == 1
    assert inside[0].entry_idx == 3


def test_split_and_drawdown():
    trades = [
        Trade(1, 2, "long", 100, 120, 20, "target"),
        Trade(3, 4, "short", 100, 110, -10, "stop"),
        Trade(5, 6, "long", 100, 90, -10, "stop"),
    ]
    longs, shorts = split_long_short(trades)
    assert len(longs) == 2 and len(shorts) == 1
    # 權益: 0,20,10,0 -> 峰20 谷0 -> 回撤 -20
    assert equity_max_drawdown(trades) == -20.0
