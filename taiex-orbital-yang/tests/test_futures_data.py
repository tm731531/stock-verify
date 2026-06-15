from orbital_yang.futures_data import select_daily_ohlc


def test_select_picks_max_volume_frontmonth_and_daysession():
    rows = [
        # 2026-06-01: 近月(量大) vs 遠月(量小); 各有日盤/盤後
        {"date": "2026-06-01", "contract_date": "202606", "open": 100, "max": 110,
         "min": 95, "close": 105, "volume": 1000, "trading_session": "position"},
        {"date": "2026-06-01", "contract_date": "202609", "open": 101, "max": 109,
         "min": 96, "close": 104, "volume": 10, "trading_session": "position"},
        {"date": "2026-06-01", "contract_date": "202606", "open": 105, "max": 112,
         "min": 104, "close": 108, "volume": 5000, "trading_session": "after_market"},
        {"date": "2026-06-02", "contract_date": "202606", "open": 106, "max": 115,
         "min": 105, "close": 113, "volume": 2000, "trading_session": "position"},
    ]
    df = select_daily_ohlc(rows)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2                          # 兩個交易日
    # 06-01 應取日盤(position)近月(量1000), 非盤後(量5000)
    row0 = df.iloc[0]
    assert row0["close"] == 105
    assert row0["high"] == 110 and row0["low"] == 95
    assert df.iloc[1]["close"] == 113
