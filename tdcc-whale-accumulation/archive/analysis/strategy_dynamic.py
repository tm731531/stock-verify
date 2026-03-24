#!/usr/bin/env python3
"""
Dynamic stop strategy scan:
  Entry: 4 weeks consecutive whale accumulation, ratio +2%, price within ±1%
  Stop loss: lowest price during accumulation period (break consolidation = exit)
  Take profit: trailing stop from peak (dynamic)
  Uses DAILY prices for precise exit timing.
"""

import sqlite3, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tdcc_holdings.db")
COST = 0.585


def load_data():
    conn = sqlite3.connect(DB_PATH, timeout=10)

    # TDCC weekly
    tdcc = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    date_counts = tdcc.groupby("date").size()
    valid_dates = sorted(date_counts[date_counts > 500].index.tolist())
    tdcc = tdcc[tdcc["date"].isin(valid_dates)]

    # Daily prices (full)
    prices = pd.read_sql(
        "SELECT stock_code, date, close_price FROM daily_prices "
        "WHERE date >= '20250301' AND date <= '20260228' ORDER BY stock_code, date",
        conn,
    )
    conn.close()

    # Build price lookup: stock -> sorted list of (date, price)
    price_dict = {}
    for stock, grp in prices.groupby("stock_code"):
        price_dict[stock] = list(zip(grp["date"].values, grp["close_price"].values))

    return tdcc, valid_dates, price_dict


def find_acc_low(price_dict, stock, start_date, end_date):
    """Find lowest daily price during accumulation period."""
    if stock not in price_dict:
        return None
    prices = [(d, p) for d, p in price_dict[stock] if start_date <= d <= end_date]
    if not prices:
        return None
    return min(p for _, p in prices)


def get_daily_prices_after(price_dict, stock, after_date, max_days=200):
    """Get daily prices after a date, up to max_days."""
    if stock not in price_dict:
        return []
    result = [(d, p) for d, p in price_dict[stock] if d > after_date]
    return result[:max_days]


def simulate_trade(daily_after, buy_price, stop_loss_price, trailing_pct):
    """
    Simulate a trade with dynamic stop loss and trailing stop.

    Returns: (exit_price, exit_date, exit_reason, days_held, peak_price)
    """
    peak = buy_price

    for i, (date, price) in enumerate(daily_after):
        peak = max(peak, price)

        # Check stop loss (break consolidation low)
        if price <= stop_loss_price:
            return price, date, "stop_loss", i + 1, peak

        # Check trailing stop (price dropped trailing_pct from peak)
        if peak > buy_price and trailing_pct > 0:
            trail_level = peak * (1 - trailing_pct / 100)
            if price <= trail_level:
                return price, date, "trailing_stop", i + 1, peak

    # End of data - exit at last price
    if daily_after:
        last_date, last_price = daily_after[-1]
        return last_price, last_date, "end_of_data", len(daily_after), peak

    return buy_price, "", "no_data", 0, peak


def simulate_trade_buffered(daily_after, buy_price, stop_loss_price, trailing_pct, sl_buffer_pct=0):
    """
    Same as simulate_trade but with stop loss buffer.
    stop_loss_price is adjusted down by sl_buffer_pct.
    """
    adjusted_sl = stop_loss_price * (1 - sl_buffer_pct / 100)
    return simulate_trade(daily_after, buy_price, adjusted_sl, trailing_pct)


def scan_and_evaluate(tdcc, valid_dates, price_dict,
                      min_weeks=4, min_ratio=2.0, max_acc_change=1.0,
                      trailing_pcts=[5, 10, 15, 20],
                      min_price=0, max_price=9999):
    """Scan signals and simulate with multiple trailing stop levels."""

    stocks = tdcc["stock_code"].unique()
    signals = []

    for stock in stocks:
        if stock.startswith("00"):
            continue
        df = tdcc[tdcc["stock_code"] == stock].sort_values("date")
        if len(df) < min_weeks + 1:
            continue

        ratios = df["ratio_400_above"].values
        dates = df["date"].values

        for i in range(min_weeks, len(ratios)):
            # Check consecutive rises
            rising = all(ratios[i - j] > ratios[i - j - 1] for j in range(min_weeks))
            if not rising:
                continue

            rc = ratios[i] - ratios[i - min_weeks]
            if rc < min_ratio:
                continue

            signal_date = dates[i]
            acc_start_date = dates[i - min_weeks]

            # Get buy price (next TDCC week)
            idx = i
            if idx + 1 >= len(dates):
                continue
            buy_date = dates[idx + 1]

            # Use daily price for buy
            if stock not in price_dict:
                continue
            daily = dict(price_dict[stock])
            buy_price = daily.get(buy_date)
            if not buy_price or buy_price <= 0:
                continue

            # Price filter
            if buy_price < min_price or buy_price > max_price:
                continue

            # Signal date price for acc change check
            signal_price = daily.get(signal_date)
            start_price = daily.get(acc_start_date)
            if not signal_price or not start_price or start_price <= 0:
                continue

            acc_change = abs((signal_price - start_price) / start_price * 100)
            if acc_change > max_acc_change:
                continue

            # Accumulation period low (stop loss level)
            acc_low = find_acc_low(price_dict, stock, acc_start_date, signal_date)
            if not acc_low:
                continue

            # Stop loss distance
            sl_distance = (acc_low - buy_price) / buy_price * 100

            # Get daily prices after buy for simulation
            daily_after = get_daily_prices_after(price_dict, stock, buy_date)

            signals.append({
                "stock": stock,
                "signal_date": signal_date,
                "buy_date": buy_date,
                "buy_price": buy_price,
                "acc_low": acc_low,
                "sl_distance": round(sl_distance, 2),
                "ratio_change": round(rc, 2),
                "acc_change": round(acc_change, 2),
                "daily_after": daily_after,
            })

    print(f"訊號數: {len(signals)}")

    if not signals:
        return

    # Simulate with different trailing stop levels and buffer combos
    sl_buffers = [0, 3, 5]
    combos = [(trail, buf) for trail in trailing_pcts for buf in sl_buffers]

    for trail, buf in combos:
        results = []
        for sig in signals:
            exit_price, exit_date, reason, days, peak = simulate_trade_buffered(
                sig["daily_after"], sig["buy_price"], sig["acc_low"], trail, buf
            )
            hold_ret = (exit_price - sig["buy_price"]) / sig["buy_price"] * 100
            net = hold_ret - COST

            results.append({
                "stock": sig["stock"],
                "buy_date": sig["buy_date"],
                "buy_price": sig["buy_price"],
                "exit_price": round(exit_price, 2),
                "exit_date": exit_date,
                "exit_reason": reason,
                "days_held": days,
                "peak": round(peak, 2),
                "hold_ret": round(hold_ret, 2),
                "net": round(net, 2),
                "sl_distance": sig["sl_distance"],
                "ratio_change": sig["ratio_change"],
            })

        df = pd.DataFrame(results)
        n = len(df)
        wins = (df["net"] > 0).sum()
        big = (df["net"] > 10).sum()
        sl = (df["exit_reason"] == "stop_loss").sum()
        ts = (df["exit_reason"] == "trailing_stop").sum()
        eod = (df["exit_reason"] == "end_of_data").sum()

        buf_label = f"+{buf}%緩衝" if buf > 0 else "無緩衝"
        print(f"\n{'='*70}")
        print(f"Trailing Stop: {trail}% | 停損: 盤整底部 {buf_label}")
        print(f"{'='*70}")
        print(f"  訊號: {n} | 勝率: {wins}/{n} ({wins/n*100:.1f}%)")
        print(f"  大勝>10%: {big} ({big/n*100:.1f}%)")
        print(f"  出場: 停損={sl} | 移動停利={ts} | 持有至今={eod}")
        print(f"  平均淨報酬: {df['net'].mean():+.2f}%")
        print(f"  中位數: {df['net'].median():+.2f}%")
        print(f"  最佳: {df['net'].max():+.2f}% | 最差: {df['net'].min():+.2f}%")
        print(f"  平均持有天數: {df['days_held'].mean():.0f}")
        print(f"  平均停損距離: {df['sl_distance'].mean():.1f}%")

        # Save to CSV
        df.to_csv(os.path.join(os.path.dirname(__file__), "data", f"dynamic_t{trail}_b{buf}.csv"), index=False)


def main():
    print("載入資料...")
    tdcc, valid_dates, price_dict = load_data()
    print(f"  TDCC: {len(valid_dates)} 週 | 日K: {len(price_dict)} 檔股票")

    # 主要測試: 4週連升, ratio>=2%, 盤整<1%, 全價位
    # trailing: 10/15/20%  x  buffer: 0/3/5%
    print(f"\n{'='*70}")
    print("條件: 4週連升, ratio>=2%, 盤整<1%, 全價位")
    print(f"{'='*70}")
    scan_and_evaluate(tdcc, valid_dates, price_dict,
                      min_weeks=4, min_ratio=2.0, max_acc_change=1.0,
                      trailing_pcts=[10, 15, 20])


if __name__ == "__main__":
    main()
