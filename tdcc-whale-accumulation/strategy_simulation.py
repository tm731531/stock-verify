#!/usr/bin/env python3
"""
Realistic portfolio simulation:
  Entry: 4 weeks consecutive whale accumulation, ratio +2%, price within ±1%
  Price range: 15-50 TWD
  Capital: 500,000 TWD
  Positions: unlimited (limited only by capital, 100K per position)
  Stop loss: accumulation period low (break consolidation)
  Take profit: 15% trailing stop from peak
  Uses DAILY prices for precise exit timing.
"""

import sqlite3, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import numpy as np
import pandas as pd
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tdcc_holdings.db")
COST_PCT = 0.585
TRAILING_PCT = 15
PER_POSITION = 100_000
INITIAL_CAPITAL = 500_000


def load_data():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    tdcc = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    date_counts = tdcc.groupby("date").size()
    valid_dates = sorted(date_counts[date_counts > 500].index.tolist())
    tdcc = tdcc[tdcc["date"].isin(valid_dates)]

    prices = pd.read_sql(
        "SELECT stock_code, date, close_price FROM daily_prices "
        "WHERE date >= '20250301' AND date <= '20260228' ORDER BY stock_code, date",
        conn,
    )
    conn.close()

    price_dict = {}
    for stock, grp in prices.groupby("stock_code"):
        price_dict[stock] = list(zip(grp["date"].values, grp["close_price"].values))

    # Build all trading dates (sorted)
    all_trade_dates = sorted(prices["date"].unique())

    return tdcc, valid_dates, price_dict, all_trade_dates


def detect_signals(tdcc, price_dict, min_weeks=4, min_ratio=2.0, max_acc_change=1.0,
                   min_price=15, max_price=50):
    """Detect all entry signals, sorted by buy_date."""
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
            rising = all(ratios[i - j] > ratios[i - j - 1] for j in range(min_weeks))
            if not rising:
                continue

            rc = ratios[i] - ratios[i - min_weeks]
            if rc < min_ratio:
                continue

            signal_date = dates[i]
            acc_start_date = dates[i - min_weeks]

            idx = i
            if idx + 1 >= len(dates):
                continue
            buy_date = dates[idx + 1]

            if stock not in price_dict:
                continue
            daily = dict(price_dict[stock])
            buy_price = daily.get(buy_date)
            if not buy_price or buy_price <= 0:
                continue

            if buy_price < min_price or buy_price > max_price:
                continue

            signal_price = daily.get(signal_date)
            start_price = daily.get(acc_start_date)
            if not signal_price or not start_price or start_price <= 0:
                continue

            acc_change = abs((signal_price - start_price) / start_price * 100)
            if acc_change > max_acc_change:
                continue

            # Accumulation low = stop loss level
            acc_prices = [p for d, p in price_dict[stock] if acc_start_date <= d <= signal_date]
            if not acc_prices:
                continue
            acc_low = min(acc_prices)

            signals.append({
                "stock": stock,
                "signal_date": signal_date,
                "buy_date": buy_date,
                "buy_price": buy_price,
                "acc_low": acc_low,
                "ratio_change": round(rc, 2),
                "acc_change": round(acc_change, 2),
            })

    signals.sort(key=lambda s: s["buy_date"])
    return signals


def run_simulation(signals, price_dict, all_trade_dates):
    """
    Walk through each trading day, manage portfolio.
    - Check exits (stop loss / trailing stop) daily
    - Process new signals on their buy_date
    - Track equity curve daily
    """
    cash = INITIAL_CAPITAL
    positions = []  # {stock, buy_date, buy_price, shares, invested, acc_low, peak}
    trades = []     # completed trades
    skipped = []    # skipped signals
    equity_log = []
    held_stocks = set()

    # Index signals by buy_date
    from collections import defaultdict
    sig_by_date = defaultdict(list)
    for s in signals:
        sig_by_date[s["buy_date"]].append(s)

    for date in all_trade_dates:
        # ── Step 1: Check exits for existing positions ──
        exited = []
        for pos in positions:
            if pos["stock"] not in price_dict:
                continue
            daily = dict(price_dict[pos["stock"]])
            price = daily.get(date)
            if not price:
                continue

            pos["peak"] = max(pos["peak"], price)

            # Stop loss: break accumulation low
            if price <= pos["acc_low"]:
                hold_ret = (price - pos["buy_price"]) / pos["buy_price"] * 100
                net = hold_ret - COST_PCT
                pnl = pos["invested"] * net / 100
                cash += pos["invested"] + pnl
                trades.append({
                    "stock": pos["stock"],
                    "buy_date": pos["buy_date"],
                    "buy_price": pos["buy_price"],
                    "exit_date": date,
                    "exit_price": round(price, 2),
                    "exit_reason": "stop_loss",
                    "hold_ret": round(hold_ret, 2),
                    "net": round(net, 2),
                    "pnl": round(pnl),
                    "peak": round(pos["peak"], 2),
                    "days": len([d for d in all_trade_dates if pos["buy_date"] < d <= date]),
                })
                exited.append(pos)
                held_stocks.discard(pos["stock"])
                continue

            # Trailing stop: 15% from peak
            if pos["peak"] > pos["buy_price"]:
                trail_level = pos["peak"] * (1 - TRAILING_PCT / 100)
                if price <= trail_level:
                    hold_ret = (price - pos["buy_price"]) / pos["buy_price"] * 100
                    net = hold_ret - COST_PCT
                    pnl = pos["invested"] * net / 100
                    cash += pos["invested"] + pnl
                    trades.append({
                        "stock": pos["stock"],
                        "buy_date": pos["buy_date"],
                        "buy_price": pos["buy_price"],
                        "exit_date": date,
                        "exit_price": round(price, 2),
                        "exit_reason": "trailing_stop",
                        "hold_ret": round(hold_ret, 2),
                        "net": round(net, 2),
                        "pnl": round(pnl),
                        "peak": round(pos["peak"], 2),
                        "days": len([d for d in all_trade_dates if pos["buy_date"] < d <= date]),
                    })
                    exited.append(pos)
                    held_stocks.discard(pos["stock"])
                    continue

        for pos in exited:
            positions.remove(pos)

        # ── Step 2: Process new signals ──
        for sig in sig_by_date.get(date, []):
            if sig["stock"] in held_stocks:
                skipped.append({**sig, "reason": "already_held"})
                continue

            if cash < PER_POSITION:
                skipped.append({**sig, "reason": "insufficient_cash"})
                continue

            shares = int(PER_POSITION / sig["buy_price"])
            invested = shares * sig["buy_price"]
            cash -= invested

            positions.append({
                "stock": sig["stock"],
                "buy_date": sig["buy_date"],
                "buy_price": sig["buy_price"],
                "shares": shares,
                "invested": invested,
                "acc_low": sig["acc_low"],
                "peak": sig["buy_price"],
            })
            held_stocks.add(sig["stock"])

        # ── Step 3: Record equity ──
        portfolio_value = cash
        for pos in positions:
            daily = dict(price_dict.get(pos["stock"], []))
            price = daily.get(date, pos["buy_price"])
            portfolio_value += pos["shares"] * price

        equity_log.append({
            "date": date,
            "equity": round(portfolio_value),
            "positions": len(positions),
            "cash": round(cash),
        })

    # Force exit remaining positions
    for pos in list(positions):
        daily = dict(price_dict.get(pos["stock"], []))
        last_price = pos["buy_price"]
        last_date = all_trade_dates[-1]
        for d in reversed(all_trade_dates):
            p = daily.get(d)
            if p:
                last_price = p
                last_date = d
                break

        hold_ret = (last_price - pos["buy_price"]) / pos["buy_price"] * 100
        net = hold_ret - COST_PCT
        pnl = pos["invested"] * net / 100
        trades.append({
            "stock": pos["stock"],
            "buy_date": pos["buy_date"],
            "buy_price": pos["buy_price"],
            "exit_date": last_date,
            "exit_price": round(last_price, 2),
            "exit_reason": "end_of_data",
            "hold_ret": round(hold_ret, 2),
            "net": round(net, 2),
            "pnl": round(pnl),
            "peak": round(pos["peak"], 2),
            "days": len([d for d in all_trade_dates if pos["buy_date"] < d <= last_date]),
        })

    return trades, skipped, equity_log


def main():
    print("載入資料...")
    tdcc, valid_dates, price_dict, all_trade_dates = load_data()
    print(f"  TDCC: {len(valid_dates)} 週 | 日K: {len(price_dict)} 檔 | 交易日: {len(all_trade_dates)}")

    print("\n偵測訊號...")
    signals = detect_signals(tdcc, price_dict)
    print(f"  訊號數: {len(signals)}")

    print("\n模擬中...")
    trades, skipped, equity_log = run_simulation(signals, price_dict, all_trade_dates)

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_log)
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame()

    # Save
    trades_df.to_csv(os.path.join(os.path.dirname(__file__), "data", "sim_trades.csv"), index=False)
    equity_df.to_csv(os.path.join(os.path.dirname(__file__), "data", "sim_equity.csv"), index=False)

    # ── Results ──
    n = len(trades_df)
    final_equity = equity_df.iloc[-1]["equity"] if len(equity_df) > 0 else INITIAL_CAPITAL
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    total_pnl = trades_df["pnl"].sum() if n > 0 else 0
    peak_equity = equity_df["equity"].max() if len(equity_df) > 0 else INITIAL_CAPITAL
    trough_equity = equity_df["equity"].min() if len(equity_df) > 0 else INITIAL_CAPITAL
    max_positions = equity_df["positions"].max() if len(equity_df) > 0 else 0
    max_dd_from_peak = (trough_equity - peak_equity) / peak_equity * 100 if peak_equity > 0 else 0

    wins = (trades_df["net"] > 0).sum() if n else 0
    big_wins = (trades_df["net"] > 10).sum() if n else 0
    sl_count = (trades_df["exit_reason"] == "stop_loss").sum() if n else 0
    ts_count = (trades_df["exit_reason"] == "trailing_stop").sum() if n else 0
    eod_count = (trades_df["exit_reason"] == "end_of_data").sum() if n else 0

    skip_cash = len(skipped_df[skipped_df["reason"] == "insufficient_cash"]) if len(skipped_df) > 0 else 0
    skip_held = len(skipped_df[skipped_df["reason"] == "already_held"]) if len(skipped_df) > 0 else 0

    print(f"\n{'='*70}")
    print(f"實戰模擬結果")
    print(f"{'='*70}")
    print(f"  策略: 4週連升 ratio>=2% | 盤整<1% | 15-50元")
    print(f"  出場: 盤整底停損 + 15% trailing stop")
    print(f"  資金: {INITIAL_CAPITAL:,} TWD | 每檔 {PER_POSITION:,} | 不限檔數")
    print(f"")
    print(f"  初始資金: {INITIAL_CAPITAL:,}")
    print(f"  最終淨值: {final_equity:,}")
    print(f"  總報酬率: {total_return:+.2f}%")
    print(f"  總損益: {total_pnl:+,.0f} TWD")
    print(f"  最高淨值: {peak_equity:,}")
    print(f"  最大回撤: {max_dd_from_peak:.1f}%")
    print(f"  最多同時持倉: {max_positions} 檔")
    print(f"")
    print(f"  訊號: {len(signals)} | 執行: {n} | 跳過(資金不足): {skip_cash} | 跳過(已持有): {skip_held}")
    print(f"  勝率: {wins}/{n} ({wins/n*100:.1f}%)" if n else "  無交易")
    if n:
        print(f"  大勝>10%: {big_wins} ({big_wins/n*100:.1f}%)")
        print(f"  出場: 停損={sl_count} | 移動停利={ts_count} | 持有至今={eod_count}")
        print(f"  平均淨報酬: {trades_df['net'].mean():+.2f}%")
        print(f"  中位數: {trades_df['net'].median():+.2f}%")
        print(f"  最佳: {trades_df['net'].max():+.2f}% | 最差: {trades_df['net'].min():+.2f}%")
        print(f"  平均持有: {trades_df['days'].mean():.0f} 天")

    # Trade details
    print(f"\n逐筆交易:")
    if n:
        for _, r in trades_df.sort_values("buy_date").iterrows():
            mark = "W" if r["net"] > 10 else ("S" if r["exit_reason"] == "stop_loss" else "T" if r["exit_reason"] == "trailing_stop" else " ")
            print(
                f"  [{mark}] {r['stock']:>6} | {r['buy_date']} {r['buy_price']:>6.1f}"
                f" → {r['exit_date']} {r['exit_price']:>6.1f}"
                f" | {r['net']:>+6.2f}% | {r['pnl']:>+7,} | {r['days']:>3}天"
                f" | peak {r['peak']:>6.1f} | {r['exit_reason']}"
            )

    # Weekly equity curve (sample)
    print(f"\n持倉淨值變化 (每週):")
    if len(equity_df) > 0:
        # Sample every ~5 trading days
        for i in range(0, len(equity_df), 5):
            row = equity_df.iloc[i]
            bar = "#" * row["positions"]
            ret = (row["equity"] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
            print(f"  {row['date']} | {row['positions']:>2} 檔 {bar:<6} | {row['equity']:>9,} ({ret:>+5.1f}%) | 現金 {row['cash']:>9,}")
        # Always show last
        row = equity_df.iloc[-1]
        ret = (row["equity"] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        print(f"  {row['date']} | {row['positions']:>2} 檔 {'#'*row['positions']:<6} | {row['equity']:>9,} ({ret:>+5.1f}%) | 現金 {row['cash']:>9,}")

    # Save summary
    summary = {
        "strategy": "4w_r2_acc1_15-50_trail15_sl-acclow",
        "run_date": datetime.now().isoformat(),
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(final_equity),
        "total_return_pct": round(total_return, 2),
        "total_pnl": round(total_pnl),
        "peak_equity": round(peak_equity),
        "max_drawdown_pct": round(max_dd_from_peak, 1),
        "max_positions": int(max_positions),
        "total_signals": len(signals),
        "executed": n,
        "skipped_cash": skip_cash,
        "skipped_held": skip_held,
        "win_rate": round(wins / n * 100, 1) if n else 0,
        "avg_net_return": round(float(trades_df["net"].mean()), 2) if n else 0,
        "median_return": round(float(trades_df["net"].median()), 2) if n else 0,
    }
    with open(os.path.join(os.path.dirname(__file__), "data", "sim_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n已存檔: data/sim_trades.csv, data/sim_equity.csv, data/sim_summary.json")


if __name__ == "__main__":
    main()
