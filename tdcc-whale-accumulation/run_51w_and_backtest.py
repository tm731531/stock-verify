#!/usr/bin/env python3
"""
51-week full crawl + v4 strategy backtest with portfolio management.

1. Crawl all ~2300 stocks x 51 weeks (incremental, skips existing)
2. Fetch price data for all dates
3. Detect signals (3-week consecutive whale accumulation in flat price)
4. Simulate portfolio: max positions, capital limit, hold period, stop loss
5. Output results
"""

import json
import logging
import os
import sys
import time
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from crawler.main import TDCCCrawler
from crawler.price_fetcher import PriceFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "strategy_config.json")
RESULTS_FILE = os.path.join(DATA_DIR, "v4_backtest_51w.json")

HOLD_WEEKS = 9  # ~60 trading days


# -- Phase 1: Crawl ---------------------------------------------------------

def phase1_crawl():
    """Crawl all stocks x 51 weeks (incremental)."""
    logger.info("=" * 60)
    logger.info("Phase 1: TDCC 51 週全量爬取（增量模式）")
    logger.info("=" * 60)

    crawler = TDCCCrawler(data_dir=DATA_DIR, request_delay=0.3)
    crawler.scraper.init_session()

    stats = crawler.crawl(max_dates=51, incremental=True)
    logger.info(f"Phase 1 完成: {stats}")

    conn = sqlite3.connect(os.path.join(DATA_DIR, "tdcc_holdings.db"))
    counts = pd.read_sql(
        "SELECT date, COUNT(*) as n FROM holdings GROUP BY date ORDER BY date", conn
    )
    conn.close()

    full_dates = counts[counts["n"] > 1000]
    logger.info(f"全量日期（>1000檔）: {len(full_dates)} / {len(counts)} 週")
    return stats


# -- Phase 2: Backtest with portfolio management ----------------------------

def detect_signals(tdcc, entry, fetcher, valid_dates):
    """Scan all stocks for entry signals. Returns list of signal dicts sorted by date."""
    signals = []
    stocks = tdcc["stock_code"].unique()

    for stock in stocks:
        if entry["exclude_etf"] and stock.startswith("00"):
            continue

        stock_df = tdcc[tdcc["stock_code"] == stock].sort_values("date")
        if len(stock_df) < 4:
            continue

        ratios = stock_df["ratio_400_above"].values
        dates = stock_df["date"].values

        for i in range(3, len(ratios)):
            if not (ratios[i] > ratios[i - 1] > ratios[i - 2] > ratios[i - 3]):
                continue

            rc = ratios[i] - ratios[i - 3]
            if rc < entry["min_ratio_change_pct"]:
                continue

            start_date = dates[i - 3]
            signal_date = dates[i]

            sp = fetcher._cache.get(start_date, {}).get(stock)
            ep = fetcher._cache.get(signal_date, {}).get(stock)
            if not sp or not ep or sp <= 0:
                continue

            if ep < entry["min_stock_price"] or ep > entry["max_stock_price"]:
                continue

            price_change = (ep - sp) / sp * 100
            if abs(price_change) > entry["max_price_change_during_acc_pct"]:
                continue

            # Need at least one more date after signal for buy
            signal_idx = list(dates).index(signal_date)
            if signal_idx + 1 >= len(dates):
                continue

            buy_date = dates[signal_idx + 1]
            buy_price = fetcher._cache.get(buy_date, {}).get(stock)
            if not buy_price or buy_price <= 0:
                continue

            signals.append({
                "stock": stock,
                "signal_date": signal_date,
                "buy_date": buy_date,
                "buy_price": round(buy_price, 2),
                "ratio_change": round(rc, 2),
                "price_during_acc": round(price_change, 2),
                "signal_idx": signal_idx,
                "stock_dates": dates,  # reference for exit price lookup
            })

    signals.sort(key=lambda s: s["buy_date"])
    logger.info(f"原始訊號數: {len(signals)}")
    return signals


def simulate_portfolio(signals, fetcher, config):
    """
    Walk through time, manage positions with capital and slot constraints.

    Returns (trades, skipped_signals, portfolio_equity_curve).
    """
    max_positions = config["position_sizing"]["max_positions"]
    total_capital = config["position_sizing"]["total_capital"]
    per_position = config["position_sizing"]["per_position"]
    stop_loss_pct = config["exit_conditions"]["stop_loss_pct"]
    round_trip_cost = config["transaction_costs"]["round_trip_pct"]

    cash = total_capital
    positions = []   # list of {stock, buy_date, buy_price, shares, invested}
    trades = []      # completed trades
    skipped = []     # signals skipped due to full portfolio or insufficient cash
    equity_log = []  # weekly equity snapshots

    # Group signals by buy_date
    from collections import defaultdict
    signals_by_date = defaultdict(list)
    for sig in signals:
        signals_by_date[sig["buy_date"]].append(sig)

    # Get all dates in chronological order
    all_dates = sorted(set(
        [s["buy_date"] for s in signals] +
        [d for s in signals for d in s["stock_dates"]]
    ))

    held_stocks = set()  # stocks currently in portfolio

    for date in all_dates:
        # -- Step 1: Check exits for existing positions --
        exited = []
        for pos in positions:
            current_price = fetcher._cache.get(date, {}).get(pos["stock"])
            weeks_held = 0
            # Count weeks since buy
            for d in all_dates:
                if d > pos["buy_date"] and d <= date:
                    weeks_held += 1

            hit_stop = False
            if current_price and pos["buy_price"] > 0:
                unrealized = (current_price - pos["buy_price"]) / pos["buy_price"] * 100
                if unrealized <= stop_loss_pct:
                    hit_stop = True

            if weeks_held >= HOLD_WEEKS or hit_stop:
                exit_price = current_price if current_price else pos["buy_price"]
                hold_return = (exit_price - pos["buy_price"]) / pos["buy_price"] * 100

                if hit_stop:
                    net_return = stop_loss_pct - round_trip_cost
                    exit_reason = "stop_loss"
                else:
                    net_return = hold_return - round_trip_cost
                    exit_reason = "hold_period"

                pnl = pos["invested"] * net_return / 100
                cash += pos["invested"] + pnl

                trades.append({
                    "stock": pos["stock"],
                    "buy_date": pos["buy_date"],
                    "buy_price": pos["buy_price"],
                    "exit_date": date,
                    "exit_price": round(exit_price, 2),
                    "weeks_held": weeks_held,
                    "exit_reason": exit_reason,
                    "hold_return": round(hold_return, 2),
                    "net_return": round(net_return, 2),
                    "pnl_twd": round(pnl),
                })

                exited.append(pos)
                held_stocks.discard(pos["stock"])

        for pos in exited:
            positions.remove(pos)

        # -- Step 2: Process new signals for this date --
        for sig in signals_by_date.get(date, []):
            # Skip if already holding this stock
            if sig["stock"] in held_stocks:
                skipped.append({**sig, "skip_reason": "already_held"})
                continue

            # Check capacity
            if len(positions) >= max_positions:
                skipped.append({**sig, "skip_reason": "full_positions"})
                continue

            if cash < per_position:
                skipped.append({**sig, "skip_reason": "insufficient_cash"})
                continue

            # Buy
            shares = int(per_position / sig["buy_price"])
            invested = shares * sig["buy_price"]
            cash -= invested

            positions.append({
                "stock": sig["stock"],
                "buy_date": sig["buy_date"],
                "buy_price": sig["buy_price"],
                "shares": shares,
                "invested": invested,
            })
            held_stocks.add(sig["stock"])

        # -- Step 3: Record equity --
        portfolio_value = cash
        for pos in positions:
            cp = fetcher._cache.get(date, {}).get(pos["stock"])
            if cp:
                portfolio_value += pos["shares"] * cp
            else:
                portfolio_value += pos["invested"]

        equity_log.append({"date": date, "equity": round(portfolio_value), "positions": len(positions), "cash": round(cash)})

    # Force-exit any remaining positions at last available price
    for pos in list(positions):
        last_price = None
        for d in reversed(all_dates):
            p = fetcher._cache.get(d, {}).get(pos["stock"])
            if p:
                last_price = p
                break
        if not last_price:
            last_price = pos["buy_price"]

        hold_return = (last_price - pos["buy_price"]) / pos["buy_price"] * 100
        net_return = hold_return - round_trip_cost
        pnl = pos["invested"] * net_return / 100

        trades.append({
            "stock": pos["stock"],
            "buy_date": pos["buy_date"],
            "buy_price": pos["buy_price"],
            "exit_date": all_dates[-1],
            "exit_price": round(last_price, 2),
            "weeks_held": "open",
            "exit_reason": "end_of_data",
            "hold_return": round(hold_return, 2),
            "net_return": round(net_return, 2),
            "pnl_twd": round(pnl),
        })

    return trades, skipped, equity_log


def phase2_backtest():
    """Run v4 strategy backtest with proper portfolio management."""
    logger.info("=" * 60)
    logger.info("Phase 2: v4 盤整吃貨策略回測（含持倉管理）")
    logger.info("=" * 60)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    entry = config["entry_conditions"]

    # Load TDCC data
    conn = sqlite3.connect(os.path.join(DATA_DIR, "tdcc_holdings.db"))
    tdcc = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    conn.close()

    date_counts = tdcc.groupby("date").size()
    valid_dates = sorted(date_counts[date_counts > 500].index.tolist())
    tdcc = tdcc[tdcc["date"].isin(valid_dates)]
    logger.info(f"有效日期: {len(valid_dates)} 週，總記錄: {len(tdcc)}")

    # Fetch price data (uses SQLite cache, only hits API for missing dates)
    db_path = os.path.join(DATA_DIR, "tdcc_holdings.db")
    fetcher = PriceFetcher(request_delay=0.3, db_path=db_path)
    logger.info(f"載入/抓取 {len(valid_dates)} 個日期的股價...")
    for d in valid_dates:
        fetcher.fetch_market_day(d)
        time.sleep(0.1)
    logger.info(f"股價完成，{len(fetcher._cache)} 個日期")

    # Detect all signals
    signals = detect_signals(tdcc, entry, fetcher, valid_dates)

    if not signals:
        logger.warning("沒有找到符合條件的訊號！")
        return

    # Simulate portfolio
    trades, skipped, equity_log = simulate_portfolio(signals, fetcher, config)

    # -- Results --
    trades_df = pd.DataFrame(trades)
    skipped_df = pd.DataFrame(skipped) if skipped else pd.DataFrame()
    equity_df = pd.DataFrame(equity_log)

    # Save raw data
    trades_df.to_csv(os.path.join(DATA_DIR, "v4_trades_51w.csv"), index=False)
    equity_df.to_csv(os.path.join(DATA_DIR, "v4_equity_51w.csv"), index=False)
    if len(skipped_df) > 0:
        skipped_df[["stock", "buy_date", "buy_price", "skip_reason"]].to_csv(
            os.path.join(DATA_DIR, "v4_skipped_51w.csv"), index=False
        )

    # Stats
    total_capital = config["position_sizing"]["total_capital"]
    executed = len(trades_df)
    skip_full = len(skipped_df[skipped_df["skip_reason"] == "full_positions"]) if len(skipped_df) > 0 else 0
    skip_cash = len(skipped_df[skipped_df["skip_reason"] == "insufficient_cash"]) if len(skipped_df) > 0 else 0
    skip_held = len(skipped_df[skipped_df["skip_reason"] == "already_held"]) if len(skipped_df) > 0 else 0

    if executed > 0:
        rets = trades_df["net_return"].values
        pnls = trades_df["pnl_twd"].values
        winners = (trades_df["hold_return"] > 0).sum()
        big_winners = (trades_df["hold_return"] > 10).sum()
        stopped = (trades_df["exit_reason"] == "stop_loss").sum()

        final_equity = equity_df.iloc[-1]["equity"] if len(equity_df) > 0 else total_capital
        total_return = (final_equity - total_capital) / total_capital * 100
    else:
        rets = np.array([])
        pnls = np.array([])
        winners = big_winners = stopped = 0
        final_equity = total_capital
        total_return = 0

    results = {
        "run_date": datetime.now().isoformat(),
        "data_weeks": len(valid_dates),
        "total_signals": len(signals),
        "executed_trades": executed,
        "skipped_full_positions": skip_full,
        "skipped_insufficient_cash": skip_cash,
        "skipped_already_held": skip_held,
        "win_count": int(winners),
        "win_rate_pct": round(winners / executed * 100, 1) if executed else 0,
        "big_win_count": int(big_winners),
        "big_win_rate_pct": round(big_winners / executed * 100, 1) if executed else 0,
        "stopped_out": int(stopped),
        "avg_return_pct": round(float(rets.mean()), 2) if len(rets) else 0,
        "median_return_pct": round(float(np.median(rets)), 2) if len(rets) else 0,
        "best_trade_pct": round(float(rets.max()), 2) if len(rets) else 0,
        "worst_trade_pct": round(float(rets.min()), 2) if len(rets) else 0,
        "total_pnl_twd": round(float(pnls.sum())) if len(pnls) else 0,
        "final_equity_twd": round(final_equity),
        "total_return_pct": round(total_return, 2),
        "initial_capital_twd": total_capital,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("v4 回測結果（含持倉管理）")
    logger.info("=" * 60)
    logger.info(f"  初始資金: {total_capital:,} TWD")
    logger.info(f"  最終淨值: {round(final_equity):,} TWD")
    logger.info(f"  總報酬率: {total_return:+.2f}%")
    logger.info(f"  總損益: {round(float(pnls.sum())) if len(pnls) else 0:+,} TWD")
    logger.info("")
    logger.info(f"  訊號總數: {len(signals)}")
    logger.info(f"  實際執行: {executed}")
    logger.info(f"  跳過(滿倉): {skip_full}")
    logger.info(f"  跳過(資金不足): {skip_cash}")
    logger.info(f"  跳過(已持有): {skip_held}")
    logger.info("")
    if executed:
        logger.info(f"  勝率: {winners}/{executed} ({winners/executed*100:.1f}%)")
        logger.info(f"  大勝(>10%): {big_winners}/{executed} ({big_winners/executed*100:.1f}%)")
        logger.info(f"  停損出場: {stopped}")
        logger.info(f"  平均淨報酬: {rets.mean():+.2f}%")
        logger.info(f"  中位數淨報酬: {np.median(rets):+.2f}%")
        logger.info(f"  最佳: {rets.max():+.2f}%  最差: {rets.min():+.2f}%")

    # Trade details
    logger.info("")
    logger.info("逐筆交易明細:")
    for _, r in trades_df.sort_values("buy_date").iterrows():
        mark = "W" if r["hold_return"] > 10 else ("S" if r["exit_reason"] == "stop_loss" else " ")
        logger.info(
            f"  [{mark}] {r['stock']:>8} | 買{r['buy_date']} {r['buy_price']:>6.1f} "
            f"→ 賣{r['exit_date']} {r['exit_price']:>6.1f} | "
            f"{r['net_return']:+.2f}% | {r['pnl_twd']:+,} TWD | {r['exit_reason']}"
        )

    # Equity curve summary
    if len(equity_df) > 0:
        logger.info("")
        logger.info("持倉變化:")
        for _, row in equity_df.iterrows():
            bar = "#" * row["positions"]
            logger.info(f"  {row['date']} | 持倉:{row['positions']} {bar:5s} | 淨值:{row['equity']:>9,} | 現金:{row['cash']:>9,}")

    return results


# -- Main --------------------------------------------------------------------

if __name__ == "__main__":
    start = time.time()

    if "--skip-crawl" in sys.argv:
        logger.info("跳過爬取，直接回測")
    else:
        phase1_crawl()

    phase2_backtest()

    elapsed = time.time() - start
    logger.info(f"\n總耗時: {elapsed / 60:.1f} 分鐘")
