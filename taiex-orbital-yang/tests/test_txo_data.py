import pandas as pd
from orbital_yang.txo_data import pick_entry_option, lookup_premium


def _chain():
    return pd.DataFrame([
        {"contract_date": "202606F2", "strike_price": 44000, "call_put": "call",
         "close": 120, "volume": 500, "trading_session": "position"},
        {"contract_date": "202606F2", "strike_price": 44500, "call_put": "call",
         "close": 32, "volume": 800, "trading_session": "position"},
        {"contract_date": "202606F2", "strike_price": 44600, "call_put": "call",
         "close": 28, "volume": 300, "trading_session": "position"},
        {"contract_date": "202606F2", "strike_price": 44500, "call_put": "call",
         "close": 40, "volume": 9999, "trading_session": "after_market"},  # 盤後, 應排除
        {"contract_date": "202606F2", "strike_price": 43000, "call_put": "put",
         "close": 30, "volume": 100, "trading_session": "position"},
    ])


def test_pick_entry_option_nearest_30_call():
    opt = pick_entry_option(_chain(), "call", 30.0)
    # 44500(32, 距2) vs 44600(28, 距2) -> 同距離取量大者 44500(800>300)
    assert opt["strike_price"] == 44500
    assert opt["close"] == 32
    assert opt["call_put"] == "call"


def test_lookup_premium_found_and_missing():
    ch = _chain()
    assert lookup_premium(ch, "202606F2", 44500, "call") == 32
    assert lookup_premium(ch, "202606F2", 99999, "call") is None   # 不存在
