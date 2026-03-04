"""
對比回測: 90交易日到期 vs 日曆3個月到期
"""
import sys
import pandas as pd
import numpy as np
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from strategy_v6d import (
    load_data, prepare_data, scan_signals,
    StrategyConfig, Signal, Position, Trade, PortfolioResult
)

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'


def simulate_portfolio_calendar(signals, price_idx, prices, cfg, use_calendar_months=False):
    """模擬投組，支援 90交易日 或 日曆3個月 到期"""
    cash = cfg.capital
    positions = []
    trades = []
    held_codes = set()
    weekly_entries = defaultdict(int)

    sig_by_date = defaultdict(list)
    for s in signals:
        sig_by_date[s.buy_date].append(s)

    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        new_positions = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None:
                new_positions.append(pos)
                continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_positions.append(pos)
                continue

            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)

            ret_pct = (cp - pos.buy_price) / pos.buy_price * 100
            drawdown_pct = (cp - pos.peak_price) / pos.peak_price * 100
            peak_gain_pct = (pos.peak_price - pos.buy_price) / pos.buy_price * 100

            # 到期判斷
            if use_calendar_months:
                buy_dt = pd.Timestamp(str(pos.buy_date))
                cur_dt = pd.Timestamp(str(date))
                expired = cur_dt >= buy_dt + pd.DateOffset(months=3)
            else:
                expired = pos.days_held >= cfg.max_hold_days

            exit_reason = None
            if ret_pct <= cfg.stop_loss_pct:
                exit_reason = '停損'
            elif peak_gain_pct >= cfg.trailing_activate_pct and drawdown_pct <= -cfg.trailing_stop_pct:
                exit_reason = '停利' if ret_pct > 0 else '追蹤停損'
            elif expired:
                exit_reason = '到期'

            if exit_reason:
                sell_value = pos.shares * cp
                sell_cost = sell_value * cfg.sell_cost_rate
                net_proceeds = sell_value - sell_cost
                profit = net_proceeds - pos.cost_basis
                cash += net_proceeds
                held_codes.discard(pos.code)
                trades.append(Trade(
                    code=pos.code, buy_date=pos.buy_date, sell_date=date,
                    buy_price=pos.buy_price, sell_price=cp, shares=pos.shares,
                    return_pct=ret_pct, profit=profit, days_held=pos.days_held,
                    exit_reason=exit_reason, peak_price=pos.peak_price,
                ))
            else:
                new_positions.append(pos)

        positions = new_positions

        if date in sig_by_date:
            week_key = str(date)[:6]
            for sig in sig_by_date[date]:
                if sig.code in held_codes:
                    continue
                if len(positions) >= cfg.max_positions:
                    continue
                if cash < cfg.per_position:
                    continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week:
                    continue
                shares = int(cfg.per_position / sig.buy_price)
                if shares <= 0:
                    continue
                cost_basis = shares * sig.buy_price * (1 + cfg.buy_fee_rate)
                if cost_basis > cash:
                    continue
                cash -= cost_basis
                positions.append(Position(
                    code=sig.code, buy_date=date, buy_price=sig.buy_price,
                    shares=shares, cost_basis=cost_basis, peak_price=sig.buy_price,
                ))
                held_codes.add(sig.code)
                weekly_entries[week_key] += 1

        portfolio_value = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                if idx < len(parr) and parr[idx, 0] == date:
                    portfolio_value += pos.shares * float(parr[idx, 1])
                else:
                    portfolio_value += pos.shares * pos.buy_price
            else:
                portfolio_value += pos.shares * pos.buy_price

        equity_records.append({'date': date, 'value': portfolio_value, 'n_positions': len(positions)})

    # 結算未平倉
    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret_pct = (cp - pos.buy_price) / pos.buy_price * 100
        profit = pos.shares * cp - pos.cost_basis
        trades.append(Trade(
            code=pos.code, buy_date=pos.buy_date, sell_date='OPEN',
            buy_price=pos.buy_price, sell_price=cp, shares=pos.shares,
            return_pct=ret_pct, profit=profit, days_held=pos.days_held,
            exit_reason='未平倉', peak_price=pos.peak_price,
        ))

    eq = pd.DataFrame(equity_records)
    peak = eq['value'].expanding().max()
    dd = (eq['value'] - peak) / peak * 100
    max_dd = dd.min()

    return PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=eq['value'].iloc[-1],
        total_return_pct=(eq['value'].iloc[-1] - cfg.capital) / cfg.capital * 100,
        max_drawdown_pct=max_dd,
        max_dd_date=eq.loc[dd.idxmin(), 'date'] if len(eq) > 0 else '',
    )


def summary(label, result, cfg):
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0
    avg_win = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.return_pct for t in losses]) if losses else 0
    pr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"\n{'═'*55}")
    print(f"  {label}")
    print(f"{'═'*55}")
    print(f"  總報酬:   {result.total_return_pct:+.1f}%  ({cfg.capital:,.0f} → {result.final_value:,.0f})")
    print(f"  最大回撤: {result.max_drawdown_pct:.1f}%")
    print(f"  已平倉:   {len(closed)} 筆 | 勝率: {wr:.0f}% | 盈虧比: {pr:.1f}")
    print(f"  贏均: {avg_win:+.1f}%  |  虧均: {avg_loss:+.1f}%")

    # 按出場原因統計
    from collections import Counter
    reasons = Counter(t.exit_reason for t in closed)
    print(f"  出場原因: " + " | ".join(f"{k}:{v}" for k, v in reasons.items()))

    # 到期的交易明細
    expired = [t for t in closed if t.exit_reason == '到期']
    if expired:
        print(f"\n  【到期出場明細】")
        for t in expired:
            icon = '🟢' if t.profit > 0 else '🔴'
            print(f"    {icon} {t.code}  買:{t.buy_date} 賣:{t.sell_date}"
                  f"  {t.return_pct:+.1f}%  {t.days_held}d")


if __name__ == '__main__':
    print("  載入資料...")
    holdings, prices = load_data()
    cfg = StrategyConfig()
    holdings, price_idx, special_flag = prepare_data(holdings, prices, cfg)
    signals = scan_signals(holdings, price_idx, cfg, special_flag)
    print(f"  訊號數: {len(signals)}")

    print("\n  跑 原版 (90交易日)...")
    r_orig = simulate_portfolio_calendar(signals, price_idx, prices, cfg, use_calendar_months=False)

    print("  跑 修改版 (日曆3個月)...")
    r_3m = simulate_portfolio_calendar(signals, price_idx, prices, cfg, use_calendar_months=True)

    summary("原版：90 交易日到期", r_orig, cfg)
    summary("修改版：日曆 3 個月到期", r_3m, cfg)

    print(f"\n{'─'*55}")
    diff = r_3m.total_return_pct - r_orig.total_return_pct
    print(f"  報酬差異: {diff:+.1f}%  ({'3個月版較好' if diff > 0 else '90交易日版較好'})")
    diff_dd = r_3m.max_drawdown_pct - r_orig.max_drawdown_pct
    print(f"  回撤差異: {diff_dd:+.1f}%  ({'3個月版較小' if diff_dd > 0 else '3個月版較大'})")
