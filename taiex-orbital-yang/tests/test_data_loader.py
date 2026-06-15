import pandas as pd
from orbital_yang.data_loader import load_daily


def _write_yf_csv(path):
    path.write_text(
        "Price,Close,High,Low,Open,Volume\n"
        "Ticker,^TWII,^TWII,^TWII,^TWII,^TWII\n"
        "2026-01-02,100.0,110.0,90.0,95.0,1000\n"
        "2026-01-03,105.0,108.0,101.0,100.0,1200\n"
    )


def test_load_daily_parses_yfinance_format(tmp_path):
    csv = tmp_path / "twii.csv"
    _write_yf_csv(csv)
    df = load_daily(str(csv))

    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    # 'Ticker' noise row must be dropped
    assert (df["open"] == 95.0).iloc[0]
    assert df["close"].iloc[1] == 105.0


def _write_yf_csv_3row(path):
    path.write_text(
        "Price,Close,High,Low,Open,Volume\n"
        "Ticker,^TWII,^TWII,^TWII,^TWII,^TWII\n"
        "Date,,,,,\n"
        "2026-01-02,100.0,110.0,90.0,95.0,1000\n"
        "2026-01-03,105.0,108.0,101.0,100.0,1200\n"
    )


def test_load_daily_handles_3row_header(tmp_path):
    csv = tmp_path / "twii3.csv"
    _write_yf_csv_3row(csv)
    df = load_daily(str(csv))
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["open"].iloc[0] == 95.0
    assert df["close"].iloc[1] == 105.0
