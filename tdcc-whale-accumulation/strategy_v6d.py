"""
v6d 大戶吃貨量化策略
====================
進場: ≥2週連升 + ratio↑≥2% + sync≥50% + 散戶↓≥2% + 股價≥300
出場: -7% 停損 | 10% trailing stop
資金: 每檔 125,000 TWD | 最多 4 檔 | 每週最多進 2 檔

用法:
    python strategy_v6d.py scan          # 掃描當前訊號
    python strategy_v6d.py backtest      # 回測完整一年
    python strategy_v6d.py portfolio     # 模擬投組走勢 (含逐筆紀錄)
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import json
import sys

# ============================================================
#  策略參數 (唯一需要改的地方)
# ============================================================

@dataclass
class StrategyConfig:
    # 進場
    min_streak: int = 2             # 最少連續上升週數
    min_r400_chg: float = 2.0       # 400張+ ratio 最低累計變化 %
    min_sync: float = 0.5           # 大小戶同步性下限 (千張變化/百張變化)
    max_holder_chg: float = -2.0    # 持有人數變化上限 % (負 = 散戶走)
    min_price: float = 300.0        # 最低股價
    exclude_etf: bool = True        # 排除 ETF (00 開頭)
    max_single_week_ratio_chg: float = 5.0  # 單週 ratio 變動超過此值 = 特殊事件, 整檔排除

    # 出場
    stop_loss_pct: float = -7.0     # 停損 %
    trailing_stop_pct: float = 10.0 # 從最高價回落 % 就出場

    # 資金管理
    capital: float = 500_000        # 初始資金
    per_position: float = 125_000   # 每檔配置
    max_positions: int = 4           # 最多同時持倉 4 檔
    max_entries_per_week: int = 2   # 每週最多進場

    # 交易成本
    buy_fee_rate: float = 0.001425  # 買入手續費率
    sell_fee_rate: float = 0.001425 # 賣出手續費率
    sell_tax_rate: float = 0.003    # 證交稅率

    @property
    def sell_cost_rate(self):
        return self.sell_fee_rate + self.sell_tax_rate


DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'
CFG = StrategyConfig()

# ============================================================
#  資料載入
# ============================================================

def load_data():
    conn = sqlite3.connect(DB_PATH)
    holdings = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    prices = pd.read_sql("SELECT * FROM daily_prices ORDER BY stock_code, date", conn)
    conn.close()
    return holdings, prices


def prepare_data(holdings, prices, cfg: StrategyConfig):
    """前處理: 排除 ETF 和特殊事件, 建立價格索引"""
    if cfg.exclude_etf:
        holdings = holdings[~holdings['stock_code'].str.startswith('00')]

    holdings = holdings.sort_values(['stock_code', 'date'])
    holdings['ratio_diff'] = holdings.groupby('stock_code')['ratio_400_above'].diff()
    bad_codes = set(
        holdings[holdings['ratio_diff'].abs() > cfg.max_single_week_ratio_chg]['stock_code'].unique()
    )
    holdings = holdings[~holdings['stock_code'].isin(bad_codes)]

    price_idx = {}
    for code, grp in prices.groupby('stock_code'):
        price_idx[code] = grp.sort_values('date')[['date', 'close_price']].values

    return holdings, price_idx, bad_codes


# ============================================================
#  訊號掃描
# ============================================================

@dataclass
class Signal:
    code: str
    signal_date: str        # TDCC 公布週
    buy_date: str           # 下一個交易日 (實際買入日)
    buy_price: float
    streak: int             # 連續上升週數
    r400_chg: float         # 400張+ ratio 累計變化
    r1000_chg: float        # 1000張+ ratio 累計變化
    sync: float             # 同步性
    holder_chg_pct: float   # 持有人數變化率
    r400_abs: float         # 當前 400張+ ratio


def scan_signals(holdings, price_idx, cfg: StrategyConfig) -> list[Signal]:
    """掃描所有符合條件的進場訊號"""
    signals = []

    for code, grp in holdings.groupby('stock_code'):
        grp = grp.sort_values('date').reset_index(drop=True)
        r400 = grp['ratio_400_above'].values
        r1000 = grp['ratio_1000_above'].values
        holders = grp['total_holders'].values
        dates = grp['date'].values

        for i in range(cfg.min_streak, len(dates)):
            # 計算連續上升週數
            streak = 0
            for j in range(i, 0, -1):
                if r400[j] > r400[j - 1]:
                    streak += 1
                else:
                    break

            if streak < cfg.min_streak:
                continue

            si = i - streak  # 起漲點

            # 特徵計算
            r400_chg = r400[i] - r400[si]
            r1000_chg = r1000[i] - r1000[si]
            sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
            h_chg = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

            # 條件篩選
            if r400_chg < cfg.min_r400_chg:
                continue
            if sync < cfg.min_sync:
                continue
            if h_chg > cfg.max_holder_chg:
                continue

            # 股價檢查
            if code not in price_idx:
                continue
            parr = price_idx[code]
            pi_e = np.searchsorted(parr[:, 0], dates[i])
            if pi_e >= len(parr):
                continue
            price = float(parr[pi_e, 1])
            if price < cfg.min_price:
                continue

            # 買入日 = 訊號日之後的第一個交易日
            buy_cands = parr[parr[:, 0] > dates[i]]
            if len(buy_cands) == 0:
                continue

            signals.append(Signal(
                code=code,
                signal_date=dates[i],
                buy_date=buy_cands[0, 0],
                buy_price=float(buy_cands[0, 1]),
                streak=streak,
                r400_chg=r400_chg,
                r1000_chg=r1000_chg,
                sync=sync,
                holder_chg_pct=h_chg,
                r400_abs=r400[i],
            ))

    return sorted(signals, key=lambda s: s.buy_date)


# ============================================================
#  投組模擬
# ============================================================

@dataclass
class Position:
    code: str
    buy_date: str
    buy_price: float
    shares: int
    cost_basis: float       # 含手續費的總成本
    peak_price: float
    days_held: int = 0


@dataclass
class Trade:
    code: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    shares: int
    return_pct: float
    profit: float
    days_held: int
    exit_reason: str        # 停損 / 停利 / 未平倉
    peak_price: float


@dataclass
class PortfolioResult:
    trades: list[Trade]
    equity_curve: pd.DataFrame
    final_value: float
    total_return_pct: float
    max_drawdown_pct: float
    max_dd_date: str


def simulate_portfolio(signals: list[Signal], price_idx: dict, prices: pd.DataFrame,
                       cfg: StrategyConfig) -> PortfolioResult:
    """逐日模擬投組"""
    cash = cfg.capital
    positions: list[Position] = []
    trades: list[Trade] = []
    held_codes: set[str] = set()
    weekly_entries: dict[str, int] = defaultdict(int)

    sig_by_date = defaultdict(list)
    for s in signals:
        sig_by_date[s.buy_date].append(s)

    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        # --- 1. 檢查出場 ---
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

            exit_reason = None
            if ret_pct <= cfg.stop_loss_pct:
                exit_reason = '停損'
            elif pos.peak_price > pos.buy_price and drawdown_pct <= -cfg.trailing_stop_pct:
                exit_reason = '停利' if ret_pct > 0 else '追蹤停損'

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

        # --- 2. 檢查進場 ---
        if date in sig_by_date:
            week_key = date[:6]
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

        # --- 3. 計算淨值 ---
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

        equity_records.append({
            'date': date, 'value': portfolio_value,
            'n_positions': len(positions), 'cash': cash,
        })

    # --- 結算未平倉 ---
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
    max_dd_date = eq.loc[dd.idxmin(), 'date'] if len(eq) > 0 else ''

    return PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=eq['value'].iloc[-1],
        total_return_pct=(eq['value'].iloc[-1] - cfg.capital) / cfg.capital * 100,
        max_drawdown_pct=max_dd,
        max_dd_date=max_dd_date,
    )


# ============================================================
#  輸出格式化
# ============================================================

def print_scan_results(signals: list[Signal], cfg: StrategyConfig):
    """印出當前訊號"""
    # 只取最新 TDCC 日期的訊號
    if not signals:
        print("  沒有符合條件的訊號")
        return

    latest_date = max(s.signal_date for s in signals)
    current = [s for s in signals if s.signal_date == latest_date]

    print(f"\n  TDCC 日期: {latest_date} | 共 {len(current)} 個訊號\n")
    print(f"  {'代碼':>6} {'買入價':>8} {'連升':>4} {'r400↑':>7} {'r1000↑':>7} {'sync':>6} {'散戶':>7} {'r400%':>6}")
    print(f"  {'─' * 65}")

    for s in sorted(current, key=lambda x: -x.r400_chg):
        print(f"  {s.code:>6} {s.buy_price:>8,.1f} {s.streak:>3}週"
              f" {s.r400_chg:>+6.1f}% {s.r1000_chg:>+6.1f}% {s.sync:>5.0%}"
              f" {s.holder_chg_pct:>+6.1f}% {s.r400_abs:>5.1f}%")


def print_portfolio_result(result: PortfolioResult, cfg: StrategyConfig):
    """印出投組結果"""
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    open_pos = [t for t in result.trades if t.exit_reason == '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]

    print(f"\n{'=' * 80}")
    print(f"  v6d 策略績效 | {cfg.capital:,.0f} → {result.final_value:,.0f}"
          f" ({result.total_return_pct:+.1f}%)")
    print(f"{'=' * 80}")
    print(f"  最大回撤: {result.max_drawdown_pct:.1f}% ({result.max_dd_date})")
    print(f"  已平倉: {len(closed)} 筆 | 未平倉: {len(open_pos)} 筆")

    if closed:
        wr = len(wins) / len(closed) * 100
        avg_win = np.mean([t.return_pct for t in wins]) if wins else 0
        avg_loss = np.mean([t.return_pct for t in losses]) if losses else 0
        pr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        print(f"  勝率: {len(wins)}/{len(closed)} ({wr:.0f}%)"
              f" | 盈虧比: {pr:.1f}"
              f" | 贏均 {avg_win:+.1f}% 虧均 {avg_loss:+.1f}%")

        total_profit = sum(t.profit for t in wins)
        total_loss = sum(t.profit for t in losses)
        print(f"  獲利 {total_profit:+,.0f} | 虧損 {total_loss:+,.0f}"
              f" | 淨 {total_profit + total_loss:+,.0f}")

    # 逐筆
    print(f"\n  {'':>2}{'代碼':>6} {'買日':>10} {'賣日':>10} {'買價':>8} {'賣價':>8}"
          f" {'報酬':>7} {'損益':>10} {'天':>4} {'出場':>4}")
    print(f"  {'─' * 78}")

    for t in sorted(result.trades, key=lambda x: x.buy_date):
        icon = '🟢' if t.profit > 0 else '🔴' if t.exit_reason != '未平倉' else '⏳'
        print(f"  {icon}{t.code:>5} {t.buy_date:>10} {t.sell_date:>10}"
              f" {t.buy_price:>8,.1f} {t.sell_price:>8,.1f}"
              f" {t.return_pct:>+6.1f}% {t.profit:>+10,.0f} {t.days_held:>3}d {t.exit_reason}")


def export_signals_json(signals: list[Signal], path: str):
    """匯出訊號為 JSON (供其他程式讀取)"""
    data = [{
        'code': s.code,
        'signal_date': s.signal_date,
        'buy_date': s.buy_date,
        'buy_price': s.buy_price,
        'streak': s.streak,
        'r400_chg': round(s.r400_chg, 2),
        'r1000_chg': round(s.r1000_chg, 2),
        'sync': round(s.sync, 3),
        'holder_chg_pct': round(s.holder_chg_pct, 2),
        'r400_abs': round(s.r400_abs, 2),
    } for s in signals]

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  訊號匯出: {path} ({len(data)} 筆)")


# ============================================================
#  主程式
# ============================================================

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'

    print(f"  載入資料...")
    holdings, prices = load_data()
    holdings, price_idx, bad_codes = prepare_data(holdings, prices, CFG)
    print(f"  排除 {len(bad_codes)} 檔特殊事件股票")

    if cmd == 'scan':
        print(f"\n  策略: ≥{CFG.min_streak}週連升 | ratio↑≥{CFG.min_r400_chg}%"
              f" | sync≥{CFG.min_sync:.0%} | 散戶↓≥{abs(CFG.max_holder_chg)}%"
              f" | 股價≥{CFG.min_price:.0f}")

        signals = scan_signals(holdings, price_idx, CFG)
        print_scan_results(signals, CFG)

        # 匯出 JSON
        latest = max(s.signal_date for s in signals) if signals else ''
        current = [s for s in signals if s.signal_date == latest]
        if current:
            export_signals_json(current, str(Path(__file__).parent / 'data' / 'current_signals.json'))

    elif cmd == 'backtest':
        signals = scan_signals(holdings, price_idx, CFG)
        print(f"  訊號數: {len(signals)}")

        result = simulate_portfolio(signals, price_idx, prices, CFG)
        print_portfolio_result(result, CFG)

    elif cmd == 'portfolio':
        signals = scan_signals(holdings, price_idx, CFG)
        result = simulate_portfolio(signals, price_idx, prices, CFG)
        print_portfolio_result(result, CFG)

        # 匯出 equity curve
        eq_path = Path(__file__).parent / 'data' / 'equity_curve.csv'
        result.equity_curve.to_csv(eq_path, index=False)
        print(f"\n  淨值曲線匯出: {eq_path}")

        # 匯出交易紀錄
        trades_data = [{
            'code': t.code, 'buy_date': t.buy_date, 'sell_date': t.sell_date,
            'buy_price': t.buy_price, 'sell_price': t.sell_price,
            'shares': t.shares, 'return_pct': round(t.return_pct, 2),
            'profit': round(t.profit, 0), 'days_held': t.days_held,
            'exit_reason': t.exit_reason,
        } for t in result.trades]
        trades_path = Path(__file__).parent / 'data' / 'v6d_trades.json'
        with open(trades_path, 'w', encoding='utf-8') as f:
            json.dump(trades_data, f, ensure_ascii=False, indent=2)
        print(f"  交易紀錄匯出: {trades_path}")

    else:
        print(f"  未知指令: {cmd}")
        print(f"  用法: python {Path(__file__).name} [scan|backtest|portfolio]")


if __name__ == '__main__':
    main()
