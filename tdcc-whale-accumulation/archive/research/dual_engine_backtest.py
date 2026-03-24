#!/usr/bin/env python3
"""
Dual-Engine Strategy Backtest with 5:5 Capital Allocation

Main Engine: 3-week ratio_400_above increase ≥3% + sync ≥50% + total_holders ≤-2%
Backup Engine: 3-week retail exodus ≥15% + whale increase ≥2%

Capital allocation: 5:5 split between engines
Stop loss: -7%, Trailing stop: +15% trigger, -10% pullback
Hold period: 4 weeks
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict
import sys

# Database connection setup
def get_db_connection():
    """Create and return database connection."""
    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="tdcc",
        user="tdcc",
        password="tdcc1234"
    )

# ============================================================================
# Phase 1: Initialize and load data
# ============================================================================

print("=" * 80)
print("Dual-Engine Backtest: Main + Backup Strategy")
print("=" * 80)

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

# Load all TDCC dates
cursor.execute("""
    SELECT DISTINCT date
    FROM holdings
    ORDER BY date
""")
all_dates = sorted([row['date'] for row in cursor.fetchall()])
date_to_idx = {d: i for i, d in enumerate(all_dates)}
print(f"\n✓ Loaded {len(all_dates)} TDCC dates")

# Load all stocks
cursor.execute("""
    SELECT DISTINCT stock_code
    FROM holdings
    WHERE stock_code NOT LIKE '00%%'  -- Exclude ETFs
      AND ratio_400_above < 100        -- Exclude public takeovers
    ORDER BY stock_code
""")
all_stocks = [row['stock_code'] for row in cursor.fetchall()]
print(f"✓ Loaded {len(all_stocks)} stocks")

# Get price data for all stocks and dates
print("\nLoading price data...")
cursor.execute("""
    SELECT DISTINCT date FROM daily_prices ORDER BY date
""")
price_dates = sorted([row['date'] for row in cursor.fetchall()])
print(f"✓ Loaded {len(price_dates)} price dates")

# Close initial connection to avoid stale connection issues
conn.close()

# ============================================================================
# Phase 2: Detect signals for both engines
# ============================================================================

print("\n" + "=" * 80)
print("Phase 2: Signal Detection")
print("=" * 80)

main_signals = []  # (stock_code, signal_date, buy_date)
backup_signals = []

conn = get_db_connection()
cursor = conn.cursor(cursor_factory=RealDictCursor)

for stock_code in all_stocks:
    cursor.execute("""
        SELECT date, ratio_400_above, ratio_1000_above, total_holders
        FROM holdings
        WHERE stock_code = %s
        ORDER BY date
    """, (stock_code,))

    rows = cursor.fetchall()
    if len(rows) < 4:
        continue

    # Filter: total_holders > 5
    rows = [r for r in rows if r['total_holders'] is None or r['total_holders'] > 5]
    if len(rows) < 4:
        continue

    for i in range(3, len(rows)):
        curr_date = rows[i]['date']

        # Main Engine: 3-week consecutive ratio_400 increase >= 3%
        if (float(rows[i]['ratio_400_above'] or 0) > float(rows[i-1]['ratio_400_above'] or 0) and
            float(rows[i-1]['ratio_400_above'] or 0) > float(rows[i-2]['ratio_400_above'] or 0) and
            float(rows[i-2]['ratio_400_above'] or 0) > float(rows[i-3]['ratio_400_above'] or 0)):

            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

            if r400_chg >= 3.0:
                # Check sync ratio: ratio_1000 change / ratio_400 change >= 50%
                r1000_chg = float(rows[i]['ratio_1000_above'] or 0) - float(rows[i-3]['ratio_1000_above'] or 0)
                sync_ratio = r1000_chg / max(r400_chg, 0.001)  # Avoid division by zero

                # Check total_holders change <= -2%
                holder_chg_pct = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                                 max(float(rows[i-3]['total_holders'] or 1), 1) * 100)

                if sync_ratio >= 0.5 and holder_chg_pct <= -2.0:
                    # Get buy date (next trading day after signal)
                    if i + 1 < len(rows):
                        buy_date = rows[i + 1]['date']
                        main_signals.append((stock_code, curr_date, buy_date))

        # Backup Engine: 3-week retail exodus >= 15% + whale increase >= 2%
        if i >= 3:
            holder_chg_pct = ((float(rows[i]['total_holders'] or 0) - float(rows[i-3]['total_holders'] or 0)) /
                             max(float(rows[i-3]['total_holders'] or 1), 1) * 100)
            r400_chg = float(rows[i]['ratio_400_above'] or 0) - float(rows[i-3]['ratio_400_above'] or 0)

            if holder_chg_pct <= -15.0 and r400_chg >= 2.0:
                if i + 1 < len(rows):
                    buy_date = rows[i + 1]['date']
                    backup_signals.append((stock_code, curr_date, buy_date))

conn.close()

print(f"✓ Main engine signals: {len(main_signals)}")
print(f"✓ Backup engine signals: {len(backup_signals)}")

# ============================================================================
# Phase 3: Backtest with 5:5 capital allocation
# ============================================================================

print("\n" + "=" * 80)
print("Phase 3: Trade Simulation (5:5 Capital Split)")
print("=" * 80)

INITIAL_CAPITAL = 500_000
MAIN_CAPITAL = INITIAL_CAPITAL * 0.5  # 250,000
BACKUP_CAPITAL = INITIAL_CAPITAL * 0.5  # 250,000
STOP_LOSS_PCT = -7.0
TRAILING_ACTIVATE_PCT = 15.0
TRAILING_STOP_PCT = 10.0
HOLD_WEEKS = 4
BUY_FEE = 0.001425
SELL_FEE = 0.001425
SELL_TAX = 0.003
TOTAL_SELL_COST = SELL_FEE + SELL_TAX

def backtest_engine(signals, capital, engine_name):
    """Run backtest for one engine."""
    trades = []
    held_positions = {}  # stock -> {entry_date, entry_price, buy_date, shares}

    # Sort signals by buy_date
    signals_by_date = defaultdict(list)
    for stock_code, signal_date, buy_date in signals:
        signals_by_date[buy_date].append(stock_code)

    sorted_buy_dates = sorted(signals_by_date.keys())

    # Reconnect for trade simulation
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    for buy_date in sorted_buy_dates:
        stocks_to_buy = signals_by_date[buy_date]

        for stock_code in stocks_to_buy:
            # Skip if already holding this stock
            if stock_code in held_positions:
                continue

            # Get entry price
            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (stock_code, buy_date))

            price_row = cursor.fetchone()
            if not price_row or not price_row['close_price'] or price_row['close_price'] == 0:
                continue

            entry_price = float(price_row['close_price'])

            # Calculate shares (with buy fee)
            invested = capital / (len(stocks_to_buy) + 1)  # Simple equal allocation
            shares = int(invested / (entry_price * (1 + BUY_FEE)))

            if shares <= 0:
                continue

            actual_invested = shares * entry_price * (1 + BUY_FEE)

            held_positions[stock_code] = {
                'buy_date': buy_date,
                'entry_date': buy_date,
                'entry_price': entry_price,
                'shares': shares,
                'invested': actual_invested,
                'highest_price': entry_price,
                'trailing_activated': False,
                'trailing_high': entry_price,
            }

        # Check exits for held positions
        exit_date_idx = date_to_idx.get(buy_date, -1) + HOLD_WEEKS
        if exit_date_idx >= len(all_dates):
            exit_date_idx = len(all_dates) - 1

        exit_date = all_dates[exit_date_idx] if exit_date_idx >= 0 else buy_date

        for stock_code in list(held_positions.keys()):
            pos = held_positions[stock_code]

            # Get exit price
            cursor.execute("""
                SELECT close_price FROM daily_prices
                WHERE stock_code = %s AND date = %s
            """, (stock_code, exit_date))

            exit_row = cursor.fetchone()
            exit_price = float(exit_row['close_price']) if exit_row and exit_row['close_price'] else pos['entry_price']

            if exit_price == 0:
                exit_price = pos['entry_price']

            # Calculate return
            gross_return_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100

            # Check stop loss
            if gross_return_pct <= STOP_LOSS_PCT:
                net_return_pct = STOP_LOSS_PCT - TOTAL_SELL_COST * 100
                exit_reason = "stop_loss"
                final_price = pos['entry_price'] * (1 + STOP_LOSS_PCT / 100)
            else:
                # Check trailing stop
                if gross_return_pct >= TRAILING_ACTIVATE_PCT and not pos['trailing_activated']:
                    pos['trailing_activated'] = True
                    pos['trailing_high'] = exit_price

                if pos['trailing_activated']:
                    if (exit_price - pos['trailing_high']) / pos['trailing_high'] * 100 <= -TRAILING_STOP_PCT:
                        net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100
                        exit_reason = "trailing_stop"
                        final_price = exit_price
                    else:
                        pos['trailing_high'] = max(pos['trailing_high'], exit_price)
                        continue  # Continue holding
                else:
                    # Normal hold period exit
                    net_return_pct = gross_return_pct - TOTAL_SELL_COST * 100
                    exit_reason = "hold_period"
                    final_price = exit_price

            pnl = pos['invested'] * net_return_pct / 100

            trades.append({
                'engine': engine_name,
                'stock': stock_code,
                'entry_date': pos['entry_date'],
                'entry_price': pos['entry_price'],
                'exit_date': exit_date,
                'exit_price': final_price,
                'shares': pos['shares'],
                'gross_return_pct': gross_return_pct,
                'net_return_pct': net_return_pct,
                'pnl_twd': round(pnl),
                'exit_reason': exit_reason,
            })

            del held_positions[stock_code]

    conn.close()
    return trades

# Run backtest for both engines
main_trades = backtest_engine(main_signals, MAIN_CAPITAL, "Main")
backup_trades = backtest_engine(backup_signals, BACKUP_CAPITAL, "Backup")

all_trades = main_trades + backup_trades
trades_df = pd.DataFrame(all_trades)

print(f"\n✓ Main engine executed: {len(main_trades)} trades")
print(f"✓ Backup engine executed: {len(backup_trades)} trades")
print(f"✓ Total executed: {len(all_trades)} trades")

# ============================================================================
# Phase 4: Statistics and Reporting
# ============================================================================

print("\n" + "=" * 80)
print("BACKTEST RESULTS (5:5 Capital Allocation)")
print("=" * 80)

if len(all_trades) > 0:
    # Overall stats
    win_count = (trades_df['net_return_pct'] > 0).sum()
    win_rate = win_count / len(trades_df) * 100
    avg_return = trades_df['net_return_pct'].mean()
    median_return = trades_df['net_return_pct'].median()
    std_dev = trades_df['net_return_pct'].std()
    total_pnl = trades_df['pnl_twd'].sum()
    final_equity = INITIAL_CAPITAL + total_pnl
    total_return_pct = total_pnl / INITIAL_CAPITAL * 100

    print(f"\nOVERALL METRICS:")
    print(f"  Initial Capital: {INITIAL_CAPITAL:,.0f} TWD")
    print(f"  Final Equity: {final_equity:,.0f} TWD")
    print(f"  Total Return: {total_return_pct:+.2f}% ({total_pnl:+,.0f} TWD)")
    print(f"  Total Trades: {len(trades_df)}")
    print(f"  Win Count: {win_count}")
    print(f"  Win Rate: {win_rate:.1f}%")
    print(f"  Avg Return: {avg_return:+.2f}%")
    print(f"  Median Return: {median_return:+.2f}%")
    print(f"  Std Dev: {std_dev:.2f}%")

    # By engine
    for engine in ["Main", "Backup"]:
        engine_trades = trades_df[trades_df['engine'] == engine]
        if len(engine_trades) > 0:
            e_win = (engine_trades['net_return_pct'] > 0).sum()
            e_win_rate = e_win / len(engine_trades) * 100
            e_avg = engine_trades['net_return_pct'].mean()
            e_pnl = engine_trades['pnl_twd'].sum()

            print(f"\n{engine.upper()} ENGINE:")
            print(f"  Trades: {len(engine_trades)}")
            print(f"  Win Rate: {e_win_rate:.1f}% ({e_win}/{len(engine_trades)})")
            print(f"  Avg Return: {e_avg:+.2f}%")
            print(f"  Total PnL: {e_pnl:+,.0f} TWD")

# Save results
trades_df.to_csv('/home/tom/stock-verify/tdcc-whale-accumulation/dual_engine_backtest_results.csv', index=False)
print(f"\n✓ Results saved to dual_engine_backtest_results.csv")

print("\n" + "=" * 80)
print("✓ Backtest Complete")
print("=" * 80)
