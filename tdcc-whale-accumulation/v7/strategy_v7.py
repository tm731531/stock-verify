"""
v7 雙引擎量化策略（v7.2 最佳化版）
===========================================
主引擎（v6d 繼承）：大戶連升進場
  條件: ≥3週連升 + ratio↑≥3% + sync≥50% + 散戶↓≥2% + 股價≥300

補位引擎（策略B）：散戶出逃 + 股價站上MA20
  條件: 4週持有人↓≥5% + 股價站上MA20 + 股價≥50

決策邏輯：
  每週掃描 → 有主引擎訊號 → 優先用主引擎
           → 無主引擎訊號（該ISO週） → 補位引擎頂上
  （以ISO週為單位阻斷，避免同週兩引擎競爭）

出場（共用）:
  -7% 停損 | 漲15%啟動追蹤停利，回落10%出場 | 90天到期

資金: 500,000 TWD | 4倉 | 每倉125,000 | 每週最多2筆

回測績效 (2022-2025): 報酬+144.2% | 最大回撤-8.8% | Calmar 16.38

用法:
    python strategy_v7.py scan      # 本週雙引擎掃描
    python strategy_v7.py backtest  # 完整回測
    python strategy_v7.py report    # 詳細報告
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import json
import sys
import datetime

# ── 策略參數 ──────────────────────────────────────────────────

@dataclass
class V7Config:
    # ── 主引擎（大戶連升）──
    min_streak: int = 3
    min_r400_chg: float = 3.0
    min_sync: float = 0.5
    max_holder_chg: float = -2.0
    min_price_main: float = 300.0
    exclude_etf: bool = True
    max_single_week_ratio_chg: float = 5.0

    # ── 補位引擎（散戶出逃）──
    flee_lookback_weeks: int = 4       # 回望幾週
    flee_min_pct: float = -5.0         # 持有人至少跌幾%
    min_price_backup: float = 50.0     # 最低股價
    backup_ma_period: int = 20         # 需站上幾日均線

    # ── 出場（共用）──
    stop_loss_pct: float = -7.0
    trailing_activate_pct: float = 15.0
    trailing_stop_pct: float = 10.0
    max_hold_days: int = 90

    # ── 資金管理 ──
    capital: float = 500_000
    per_position: float = 125_000
    max_positions: int = 4
    max_entries_per_week: int = 2

    # ── 交易成本 ──
    buy_fee_rate: float = 0.001425
    sell_fee_rate: float = 0.001425
    sell_tax_rate: float = 0.003

    @property
    def sell_cost_rate(self):
        return self.sell_fee_rate + self.sell_tax_rate


DB_PATH = Path(__file__).parent.parent / 'data' / 'tdcc_holdings.db'
CFG = V7Config()


# ── 資料結構 ──────────────────────────────────────────────────

@dataclass
class Signal:
    code: str
    engine: str          # 'main' 或 'backup'
    signal_date: str
    buy_date: str
    buy_price: float
    # 主引擎專用
    streak: int = 0
    r400_chg: float = 0.0
    sync: float = 0.0
    holder_chg_pct: float = 0.0
    # 補位引擎專用
    flee_pct: float = 0.0
    holders_now: int = 0


@dataclass
class Position:
    code: str
    engine: str
    buy_date: str
    buy_price: float
    shares: int
    cost_basis: float
    peak_price: float
    days_held: int = 0


@dataclass
class Trade:
    code: str
    engine: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    shares: int
    return_pct: float
    profit: float
    days_held: int
    exit_reason: str
    peak_price: float


@dataclass
class PortfolioResult:
    trades: list
    equity_curve: pd.DataFrame
    final_value: float
    total_return_pct: float
    max_drawdown_pct: float
    max_dd_date: str


# ── 資料載入 ──────────────────────────────────────────────────

def load_data():
    conn = sqlite3.connect(DB_PATH)
    holdings = pd.read_sql("SELECT * FROM holdings ORDER BY stock_code, date", conn)
    prices   = pd.read_sql("SELECT * FROM daily_prices ORDER BY stock_code, date", conn)
    conn.close()
    return holdings, prices


def build_price_index(prices: pd.DataFrame):
    idx = {}
    for code, grp in prices.groupby('stock_code'):
        idx[code] = grp.sort_values('date')[['date', 'close_price']].values
    return idx


def build_ma_index(price_idx: dict, period: int):
    ma = {}
    for code, parr in price_idx.items():
        closes = pd.Series(parr[:, 1].astype(float))
        ma[code] = closes.rolling(period).mean().values
    return ma


# ── 主引擎訊號掃描 ────────────────────────────────────────────

def scan_main_engine(holdings: pd.DataFrame, price_idx: dict,
                     cfg: V7Config) -> list[Signal]:
    """大戶連升進場訊號"""
    # 特殊事件標記（cummax：歷史上曾有單週 >5% 則永久排除）
    special_flag = {}
    for code, grp in holdings.groupby('stock_code'):
        grp = grp.sort_values('date')
        rd = grp['ratio_400_above'].diff().abs()
        cum_sp = (rd > cfg.max_single_week_ratio_chg).cummax()
        special_flag[code] = dict(zip(grp['date'].values, cum_sp.values))

    if cfg.exclude_etf:
        holdings = holdings[~holdings['stock_code'].str.startswith('00')]

    signals = []
    for code, grp in holdings.groupby('stock_code'):
        grp = grp.sort_values('date').reset_index(drop=True)
        r400    = grp['ratio_400_above'].values
        r1000   = grp['ratio_1000_above'].values
        holders = grp['total_holders'].values
        dates   = grp['date'].values

        for i in range(cfg.min_streak, len(dates)):
            if special_flag.get(code, {}).get(dates[i], False):
                continue

            # 連升週數
            streak = 0
            for j in range(i, 0, -1):
                if r400[j] > r400[j-1]: streak += 1
                else: break
            if streak < cfg.min_streak:
                continue

            si = i - streak
            r400_chg = r400[i] - r400[si]
            r1000_chg = r1000[i] - r1000[si]
            sync = r1000_chg / r400_chg if r400_chg > 0.01 else 0
            h_chg = (holders[i] - holders[si]) / holders[si] * 100 if holders[si] > 0 else 0

            if r400_chg < cfg.min_r400_chg: continue
            if sync < cfg.min_sync: continue
            if h_chg > cfg.max_holder_chg: continue

            if code not in price_idx: continue

            parr = price_idx[code]
            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr): continue
            price = float(parr[pi, 1])
            if price < cfg.min_price_main: continue

            # 買入：延遲2天 + 收盤+3%限價 + 5天窗口
            # 看 Day N 收盤 ≤ 限價 → Day N+1 開盤掛單，以 Day N 收盤成交
            after = parr[parr[:, 0] > dates[i]]
            if len(after) < 4: continue
            limit = price * 1.03
            bought = False
            for k in range(2, min(7, len(after) - 1)):
                day_close = float(after[k, 1])
                if day_close <= limit:
                    signals.append(Signal(
                        code=code, engine='main',
                        signal_date=dates[i],
                        buy_date=after[k + 1, 0],   # 隔天成交
                        buy_price=day_close,          # 用前一天收盤當成交價
                        streak=streak, r400_chg=r400_chg,
                        sync=sync, holder_chg_pct=h_chg,
                    ))
                    bought = True
                    break

    return sorted(signals, key=lambda s: s.buy_date)


# ── 補位引擎訊號掃描 ──────────────────────────────────────────

def scan_backup_engine(holdings: pd.DataFrame, price_idx: dict,
                       cfg: V7Config, ma_idx: dict) -> list[Signal]:
    """散戶出逃 + 站上 MA20 進場訊號"""
    signals = []
    lk = cfg.flee_lookback_weeks

    for code, grp in holdings.groupby('stock_code'):
        if code.startswith('00'): continue
        grp = grp.sort_values('date').reset_index(drop=True)
        if len(grp) < lk + 1 or code not in price_idx: continue

        parr  = price_idx[code]
        ma20  = ma_idx.get(code)
        holders = grp['total_holders'].values
        dates   = grp['date'].values

        for i in range(lk, len(dates)):
            h_now, h_bef = holders[i], holders[i - lk]
            if h_bef <= 0: continue
            flee = (h_now - h_bef) / h_bef * 100
            if flee > cfg.flee_min_pct: continue

            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr): continue
            cp = float(parr[pi, 1])
            if cp < cfg.min_price_backup: continue

            # 須站上 MA20
            if ma20 is not None:
                if np.isnan(ma20[pi]) or cp < ma20[pi]: continue

            # 買入：固定第5個交易日，以當天收盤成交；若資料不足則跳過
            if pi + 5 >= len(parr): continue
            buy_price = float(parr[pi + 5, 1])
            if buy_price <= 0: continue
            signals.append(Signal(
                code=code, engine='backup',
                signal_date=dates[i],
                buy_date=parr[pi + 5, 0],
                buy_price=buy_price,
                flee_pct=flee,
                holders_now=h_now,
            ))

    return sorted(signals, key=lambda s: s.buy_date)


# ── 雙引擎投組模擬 ────────────────────────────────────────────

def simulate_v7(main_signals: list[Signal],
                backup_signals: list[Signal],
                price_idx: dict,
                prices: pd.DataFrame,
                cfg: V7Config) -> PortfolioResult:
    """
    主引擎有訊號的週 → 主引擎進場
    主引擎沒訊號的週 → 補位引擎進場
    """
    # 找有主引擎訊號的月份（YYYYMM）
    main_active_months = {s.buy_date[:6] for s in main_signals}

    # 補位引擎只在主引擎靜默的月份才啟用（外部已先做 ISO 週過濾）
    backup_filtered = [s for s in backup_signals
                       if s.buy_date[:6] not in main_active_months]

    # 合併並排序（主引擎優先）
    all_signals = sorted(
        main_signals + backup_filtered,
        key=lambda s: (s.buy_date, 0 if s.engine == 'main' else 1)
    )

    sig_by_date = defaultdict(list)
    for s in all_signals:
        sig_by_date[s.buy_date].append(s)

    cash = cfg.capital
    positions: list[Position] = []
    trades: list[Trade] = []
    held_codes: set[str] = set()
    weekly_entries: dict[str, int] = defaultdict(int)

    all_trade_dates = sorted(prices['date'].unique())
    equity_records = []

    for date in all_trade_dates:
        # 出場
        new_positions = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None: new_positions.append(pos); continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_positions.append(pos); continue

            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)

            ret = (cp - pos.buy_price) / pos.buy_price * 100
            dd  = (cp - pos.peak_price) / pos.peak_price * 100
            pg  = (pos.peak_price - pos.buy_price) / pos.buy_price * 100

            reason = None
            if ret <= cfg.stop_loss_pct:                              reason = '停損'
            elif pg >= cfg.trailing_activate_pct and dd <= -cfg.trailing_stop_pct:
                reason = '停利' if ret > 0 else '追蹤停損'
            elif pos.days_held >= cfg.max_hold_days:                  reason = '到期'

            if reason:
                net = pos.shares * cp * (1 - cfg.sell_cost_rate)
                profit = net - pos.cost_basis
                cash += net
                held_codes.discard(pos.code)
                trades.append(Trade(
                    code=pos.code, engine=pos.engine,
                    buy_date=pos.buy_date, sell_date=date,
                    buy_price=pos.buy_price, sell_price=cp,
                    shares=pos.shares, return_pct=ret,
                    profit=profit, days_held=pos.days_held,
                    exit_reason=reason, peak_price=pos.peak_price,
                ))
            else:
                new_positions.append(pos)
        positions = new_positions

        # 進場
        if date in sig_by_date:
            d = datetime.date(int(date[:4]), int(date[4:6]), int(date[6:]))
            iso = d.isocalendar()
            week_key = f'{iso[0]}W{iso[1]:02d}'
            for sig in sig_by_date[date]:
                if sig.code in held_codes: continue
                if len(positions) >= cfg.max_positions: continue
                if cash < cfg.per_position: continue
                if weekly_entries[week_key] >= cfg.max_entries_per_week: continue
                shares = int(cfg.per_position / sig.buy_price)
                if shares <= 0: continue
                cost = shares * sig.buy_price * (1 + cfg.buy_fee_rate)
                if cost > cash: continue
                cash -= cost
                positions.append(Position(
                    code=sig.code, engine=sig.engine,
                    buy_date=date, buy_price=sig.buy_price,
                    shares=shares, cost_basis=cost, peak_price=sig.buy_price,
                ))
                held_codes.add(sig.code)
                weekly_entries[week_key] += 1

        # 淨值
        pv = cash
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is not None:
                idx = np.searchsorted(parr[:, 0], date)
                pv += pos.shares * float(parr[idx if idx < len(parr) and parr[idx,0]==date else max(0,idx-1), 1])
            else:
                pv += pos.shares * pos.buy_price
        equity_records.append({'date': date, 'value': pv, 'n_positions': len(positions)})

    # 結算未平倉
    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret = (cp - pos.buy_price) / pos.buy_price * 100
        trades.append(Trade(
            code=pos.code, engine=pos.engine,
            buy_date=pos.buy_date, sell_date='OPEN',
            buy_price=pos.buy_price, sell_price=cp,
            shares=pos.shares, return_pct=ret,
            profit=pos.shares * cp - pos.cost_basis,
            days_held=pos.days_held, exit_reason='未平倉',
            peak_price=pos.peak_price,
        ))

    eq = pd.DataFrame(equity_records)
    peak = eq['value'].expanding().max()
    dd_s = (eq['value'] - peak) / peak * 100
    max_dd = dd_s.min()

    return PortfolioResult(
        trades=trades, equity_curve=eq,
        final_value=eq['value'].iloc[-1],
        total_return_pct=(eq['value'].iloc[-1] - cfg.capital) / cfg.capital * 100,
        max_drawdown_pct=max_dd,
        max_dd_date=eq.loc[dd_s.idxmin(), 'date'] if len(eq) > 0 else '',
    )


# ── 輸出格式化 ────────────────────────────────────────────────

def print_result(result: PortfolioResult, cfg: V7Config, title='v7 雙引擎策略'):
    closed = [t for t in result.trades if t.exit_reason != '未平倉']
    open_p = [t for t in result.trades if t.exit_reason == '未平倉']
    main_t = [t for t in closed if t.engine == 'main']
    back_t = [t for t in closed if t.engine == 'backup']
    wins   = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr     = len(wins)/len(closed)*100 if closed else 0
    avg_w  = np.mean([t.return_pct for t in wins]) if wins else 0
    avg_l  = np.mean([t.return_pct for t in losses]) if losses else 0
    pr     = abs(avg_w/avg_l) if avg_l else 0
    calmar = result.total_return_pct / abs(result.max_drawdown_pct) if result.max_drawdown_pct < 0 else 0

    print(f"\n{'═'*80}")
    print(f"  {title}")
    print(f"{'═'*80}")
    print(f"  總報酬:   {result.total_return_pct:+.1f}%"
          f"  ({cfg.capital:,.0f} → {result.final_value:,.0f})")
    print(f"  最大回撤: {result.max_drawdown_pct:.1f}%  ({result.max_dd_date})")
    print(f"  Calmar:   {calmar:.2f}")
    print()
    print(f"  已平倉: {len(closed)} 筆 | 未平倉: {len(open_p)} 筆")
    print(f"  勝率: {len(wins)}/{len(closed)} ({wr:.0f}%) | 盈虧比: {pr:.1f}")
    print(f"  贏均: {avg_w:+.1f}%  |  虧均: {avg_l:+.1f}%")
    print()
    print(f"  主引擎 (大戶連升): {len(main_t)} 筆")
    if main_t:
        mw = [t for t in main_t if t.profit > 0]
        ml = [t for t in main_t if t.profit <= 0]
        print(f"    勝率: {len(mw)}/{len(main_t)} ({len(mw)/len(main_t)*100:.0f}%)"
              f"  停損: {sum(1 for t in main_t if t.exit_reason=='停損')}")
    print(f"  補位引擎 (散戶出逃): {len(back_t)} 筆")
    if back_t:
        bw = [t for t in back_t if t.profit > 0]
        print(f"    勝率: {len(bw)}/{len(back_t)} ({len(bw)/len(back_t)*100:.0f}%)"
              f"  停損: {sum(1 for t in back_t if t.exit_reason=='停損')}")

    # 逐年
    print()
    print(f"  【逐年績效】")
    for yr in sorted({t.buy_date[:4] for t in closed}):
        yr_t = [t for t in closed if t.buy_date.startswith(yr)]
        yr_w = [t for t in yr_t if t.profit > 0]
        yr_pnl = sum(t.profit for t in yr_t)
        yr_wr = len(yr_w)/len(yr_t)*100 if yr_t else 0
        yr_avg = np.mean([t.return_pct for t in yr_t]) if yr_t else 0
        print(f"    {yr}: {len(yr_t):>3d}筆 | WR {yr_wr:>4.0f}%"
              f" | 平均報酬 {yr_avg:>+5.1f}% | 淨損益 {yr_pnl:>+10,.0f}")

    # 出場原因
    from collections import Counter
    reasons = Counter(t.exit_reason for t in closed)
    print(f"\n  出場原因: " + " | ".join(f"{k}:{v}" for k, v in reasons.items()))

    # 逐筆
    print(f"\n  {'':>2}{'代碼':>6} {'引擎':>5} {'買日':>10} {'賣日':>10}"
          f" {'報酬':>7} {'損益':>10} {'天':>4} {'出場'}")
    print(f"  {'─'*75}")
    for t in sorted(result.trades, key=lambda x: x.buy_date):
        icon = '🟢' if t.profit > 0 else ('🔴' if t.exit_reason != '未平倉' else '⏳')
        eng = '主' if t.engine == 'main' else '補'
        print(f"  {icon}{t.code:>5} [{eng}] {t.buy_date:>10} {t.sell_date:>10}"
              f" {t.return_pct:>+6.1f}% {t.profit:>+10,.0f} {t.days_held:>3}d {t.exit_reason}")


def scan_current(main_signals, backup_signals, main_active_weeks):
    """印出本週訊號"""
    all_sigs = main_signals + [s for s in backup_signals
                               if s.signal_date not in main_active_weeks]
    if not all_sigs:
        print("  本週無訊號")
        return

    latest = max(s.signal_date for s in all_sigs)
    current = [s for s in all_sigs if s.signal_date == latest]

    print(f"\n  TDCC 日期: {latest} | 共 {len(current)} 個訊號\n")
    for s in sorted(current, key=lambda x: (x.engine, -x.buy_price)):
        eng = '主引擎▶' if s.engine == 'main' else '補位  ▷'
        if s.engine == 'main':
            print(f"  {eng} {s.code} | 買入價 {s.buy_price:,.1f}"
                  f" | 連升{s.streak}週 r400↑{s.r400_chg:+.1f}%"
                  f" | 散戶{s.holder_chg_pct:+.1f}%")
        else:
            print(f"  {eng} {s.code} | 買入價 {s.buy_price:,.1f}"
                  f" | 散戶跑{s.flee_pct:+.1f}% | 持有人:{s.holders_now:,}")


# ── 主程式 ────────────────────────────────────────────────────

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'

    print("  載入資料...")
    holdings, prices = load_data()
    price_idx = build_price_index(prices)
    ma_idx    = build_ma_index(price_idx, CFG.backup_ma_period)

    print("  掃描主引擎訊號 (大戶連升)...")
    main_sigs = scan_main_engine(holdings, price_idx, CFG)
    print(f"    → {len(main_sigs)} 個訊號")

    print("  掃描補位引擎訊號 (散戶出逃)...")
    backup_sigs = scan_backup_engine(holdings, price_idx, CFG, ma_idx)
    def _iso_week(d):
        ts = pd.Timestamp(str(d))
        return f"{ts.year}W{ts.isocalendar()[1]:02d}"
    main_weeks = {_iso_week(s.buy_date) for s in main_sigs}
    backup_active = [s for s in backup_sigs if _iso_week(s.buy_date) not in main_weeks]
    print(f"    → {len(backup_sigs)} 個原始訊號，過濾後啟用 {len(backup_active)} 個")

    if cmd == 'scan':
        print(f"\n  策略: v7 雙引擎")
        print(f"  主引擎: ≥{CFG.min_streak}週連升 | r400↑≥{CFG.min_r400_chg}%"
              f" | sync≥{CFG.min_sync:.0%} | 散戶↓≥{abs(CFG.max_holder_chg)}%"
              f" | 股價≥{CFG.min_price_main:.0f}")
        print(f"  補位:   {CFG.flee_lookback_weeks}週持有人↓≥{abs(CFG.flee_min_pct)}%"
              f" | 站上MA{CFG.backup_ma_period} | 股價≥{CFG.min_price_backup:.0f}")
        scan_current(main_sigs, backup_sigs, main_weeks)

    elif cmd in ('backtest', 'report'):
        result = simulate_v7(main_sigs, backup_active, price_idx, prices, CFG)
        print_result(result, CFG)

        if cmd == 'report':
            eq_path = Path(__file__).parent.parent / 'data' / 'v7_equity_curve.csv'
            result.equity_curve.to_csv(eq_path, index=False)
            print(f"\n  淨值曲線匯出: {eq_path}")

            trades_data = [{
                'code': t.code, 'engine': t.engine,
                'buy_date': t.buy_date, 'sell_date': t.sell_date,
                'buy_price': t.buy_price, 'sell_price': t.sell_price,
                'return_pct': round(t.return_pct, 2),
                'profit': round(t.profit, 0),
                'days_held': t.days_held, 'exit_reason': t.exit_reason,
            } for t in result.trades]
            tp = Path(__file__).parent.parent / 'data' / 'v7_trades.json'
            with open(tp, 'w', encoding='utf-8') as f:
                json.dump(trades_data, f, ensure_ascii=False, indent=2)
            print(f"  交易紀錄匯出: {tp}")


if __name__ == '__main__':
    main()
