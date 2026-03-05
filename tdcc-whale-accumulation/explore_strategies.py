"""
探索其他策略能否達到 Calmar > 3
用現有資料測試：TDCC holdings + 日收盤價（2022-2025，~2300檔台股）

測試的策略：
A. 52週新高突破（純價格動能）
B. 散戶出逃 + 股價站上MA20（從TDCC角度出發，但邏輯完全不同）
C. 高度集中持股（大戶佔比絕對值高，非變化率）
D. 個股動能輪動（每月換股，買近3個月最強的前N%）
E. 均值回歸（RSI超賣反彈）
"""

import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import sys

DB_PATH = Path(__file__).parent / 'data' / 'tdcc_holdings.db'

# ── 通用出場邏輯 ──────────────────────────────────────
@dataclass
class Pos:
    code: str
    buy_date: str
    buy_price: float
    shares: int
    cost_basis: float
    peak_price: float
    days_held: int = 0

@dataclass
class Trd:
    code: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    return_pct: float
    profit: float
    days_held: int
    exit_reason: str


def backtest(signals_by_date: dict,  # {buy_date: [(code, buy_price), ...]}
             price_idx: dict,         # {code: ndarray [[date, price], ...]}
             all_dates: list,
             capital=500_000,
             per_position=125_000,
             max_pos=4,
             max_per_week=2,
             stop_loss=-7.0,
             trail_activate=15.0,
             trail_stop=10.0,
             max_hold=90,
             date_range=None):

    if date_range:
        s, e = date_range
        all_dates = [d for d in all_dates if s <= d <= e]

    cash = capital
    positions = []
    trades = []
    held = set()
    week_cnt = defaultdict(int)
    eq = []

    for date in all_dates:
        # 出場
        new_pos = []
        for pos in positions:
            parr = price_idx.get(pos.code)
            if parr is None:
                new_pos.append(pos); continue
            idx = np.searchsorted(parr[:, 0], date)
            if idx >= len(parr) or parr[idx, 0] != date:
                new_pos.append(pos); continue

            cp = float(parr[idx, 1])
            pos.days_held += 1
            pos.peak_price = max(pos.peak_price, cp)
            ret = (cp - pos.buy_price) / pos.buy_price * 100
            dd  = (cp - pos.peak_price) / pos.peak_price * 100
            pg  = (pos.peak_price - pos.buy_price) / pos.buy_price * 100

            reason = None
            if ret <= stop_loss:                            reason = '停損'
            elif pg >= trail_activate and dd <= -trail_stop: reason = '停利'
            elif pos.days_held >= max_hold:                  reason = '到期'

            if reason:
                net = pos.shares * cp * (1 - 0.004425)
                profit = net - pos.cost_basis
                cash += net
                held.discard(pos.code)
                trades.append(Trd(pos.code, pos.buy_date, date,
                                  pos.buy_price, cp, ret, profit, pos.days_held, reason))
            else:
                new_pos.append(pos)
        positions = new_pos

        # 進場
        for code, bp in signals_by_date.get(date, []):
            if code in held or len(positions) >= max_pos: continue
            if cash < per_position: continue
            if week_cnt[date[:6]] >= max_per_week: continue
            if bp <= 0: continue
            shares = int(per_position / bp)
            if shares <= 0: continue
            cost = shares * bp * 1.001425
            if cost > cash: continue
            cash -= cost
            positions.append(Pos(code, date, bp, shares, cost, bp))
            held.add(code)
            week_cnt[date[:6]] += 1

        pv = cash + sum(
            pos.shares * float(price_idx[pos.code][
                min(np.searchsorted(price_idx[pos.code][:, 0], date),
                    len(price_idx[pos.code])-1), 1])
            if pos.code in price_idx else pos.shares * pos.buy_price
            for pos in positions
        )
        eq.append({'date': date, 'value': pv})

    # 結算
    for pos in positions:
        parr = price_idx[pos.code]
        cp = float(parr[-1, 1])
        ret = (cp - pos.buy_price) / pos.buy_price * 100
        profit = pos.shares * cp - pos.cost_basis
        trades.append(Trd(pos.code, pos.buy_date, 'OPEN',
                          pos.buy_price, cp, ret, profit, pos.days_held, '未平倉'))

    df = pd.DataFrame(eq)
    if len(df) == 0:
        return None
    peak = df['value'].expanding().max()
    dd_s = (df['value'] - peak) / peak * 100
    max_dd = dd_s.min()
    total_ret = (df['value'].iloc[-1] - capital) / capital * 100
    calmar = total_ret / abs(max_dd) if max_dd < 0 else 0

    closed = [t for t in trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    avg_win = np.mean([t.return_pct for t in wins]) if wins else 0
    losses = [t for t in closed if t.profit <= 0]
    avg_loss = np.mean([t.return_pct for t in losses]) if losses else 0
    pr = abs(avg_win/avg_loss) if avg_loss else 0
    n_sl = sum(1 for t in closed if t.exit_reason == '停損')

    return dict(ret=total_ret, dd=max_dd, calmar=calmar,
                wr=wr, pr=pr, n=len(closed), n_sl=n_sl, trades=trades)


def show(label, m, width=40):
    if m is None:
        print(f"  {label:{width}s} | 無資料")
        return
    print(f"  {label:{width}s} | {m['ret']:>+7.1f}% | DD {m['dd']:>6.1f}% "
          f"| Calmar {m['calmar']:>5.2f} | WR {m['wr']:>4.0f}% PR {m['pr']:.1f} "
          f"| n={m['n']:>3d} SL={m['n_sl']}")


# ══════════════════════════════════════════════════════════════
print("載入資料...")
conn = sqlite3.connect(DB_PATH)
prices_df = pd.read_sql(
    "SELECT stock_code, date, close_price FROM daily_prices ORDER BY stock_code, date", conn)
holdings_df = pd.read_sql(
    "SELECT * FROM holdings ORDER BY stock_code, date", conn)
conn.close()

# 建立價格索引
price_idx = {}
for code, grp in prices_df.groupby('stock_code'):
    arr = grp.sort_values('date')[['date', 'close_price']].values
    price_idx[code] = arr

# 所有交易日
all_dates = sorted(prices_df['date'].unique())
print(f"股票數: {len(price_idx)}  交易日: {len(all_dates)}")

# ── 建立 MA 索引（MA20, MA60, MA252） ──────────────────────
print("建立 MA 索引...")
ma_idx = {}
for code, parr in price_idx.items():
    closes = pd.Series(parr[:, 1].astype(float))
    ma_idx[code] = {
        20:  closes.rolling(20).mean().values,
        60:  closes.rolling(60).mean().values,
        252: closes.rolling(252).mean().values,
    }

print()
print("=" * 95)
print("  策略探索：哪些策略能達到 Calmar > 3？")
print("=" * 95)
hdr = f"  {'策略':40s} | {'報酬':>8} | {'最大回撤':>8} | {'Calmar':>7} | {'勝率PR':>9} | n SL"
print(hdr)
print(f"  {'─'*93}")


# ══════════════════════════════════════════════════════════════
# 策略 A：52 週新高突破
# 每週五掃描：股價創 252 交易日新高 + 站上 MA20 + 股價 >= 100
# ══════════════════════════════════════════════════════════════
print("\n  【策略A：52週新高突破】")

def gen_52w_signals():
    sigs = defaultdict(list)
    for code, parr in price_idx.items():
        if len(parr) < 260:
            continue
        dates_arr = parr[:, 0]
        closes_arr = parr[:, 1].astype(float)
        ma20 = ma_idx[code][20]

        for i in range(260, len(parr)):
            date = dates_arr[i]
            cp = closes_arr[i]
            if cp < 100:
                continue
            # 創252日新高
            high252 = closes_arr[i-252:i].max()
            if cp <= high252 * 1.001:   # 剛突破，不是遠超
                continue
            if cp > high252 * 1.05:     # 突破太多，不追高
                continue
            # 站上 MA20
            if np.isnan(ma20[i]) or cp < ma20[i]:
                continue
            # 買入日（下一個交易日）
            if i + 1 < len(parr):
                buy_date = dates_arr[i+1]
                buy_price = float(closes_arr[i+1])
                sigs[buy_date].append((code, buy_price))
    return sigs

sigs_A = gen_52w_signals()
total_sigs_A = sum(len(v) for v in sigs_A.values())
print(f"  訊號數: {total_sigs_A}")

for ma_hold, sl, ta, ts, mh in [
    (None, -7.0, 15.0, 10.0, 90),
    (None, -7.0, 12.0, 8.0, 90),
    (None, -6.0, 12.0, 7.0, 60),
]:
    m = backtest(sigs_A, price_idx, all_dates, stop_loss=sl,
                 trail_activate=ta, trail_stop=ts, max_hold=mh)
    show(f"A 52W高 SL{sl}% T{ta}%@{ts}% {mh}d", m)


# ══════════════════════════════════════════════════════════════
# 策略 B：散戶大量出逃（holders 急降）+ 站上 MA20
# 大戶悄悄接貨，散戶嚇跑——底部訊號
# ══════════════════════════════════════════════════════════════
print("\n  【策略B：散戶出逃 + 股價上 MA20】")

def gen_retail_flee_signals():
    sigs = defaultdict(list)
    holdings_df_sorted = holdings_df.sort_values(['stock_code', 'date'])

    for code, grp in holdings_df_sorted.groupby('stock_code'):
        grp = grp.reset_index(drop=True)
        if len(grp) < 5:
            continue
        if code not in price_idx:
            continue
        parr = price_idx[code]
        ma20 = ma_idx[code][20]

        holders = grp['total_holders'].values
        dates = grp['date'].values

        for i in range(4, len(dates)):
            h_now = holders[i]
            h_4w  = holders[i-4]
            if h_4w <= 0:
                continue
            # 4週內持有人下降 > 5%（散戶在跑）
            flee_pct = (h_now - h_4w) / h_4w * 100
            if flee_pct > -5.0:
                continue

            # 股價要站上 MA20（代表有支撐，不是自由落體）
            pi = np.searchsorted(parr[:, 0], dates[i])
            if pi >= len(parr):
                continue
            cp = float(parr[pi, 1])
            if cp < 50:
                continue
            if np.isnan(ma20[pi]) or cp < ma20[pi]:
                continue

            # 下一週買入
            if pi + 5 < len(parr):
                buy_date = parr[pi+5, 0]
                buy_price = float(parr[pi+5, 1])
                sigs[buy_date].append((code, buy_price))
    return sigs

sigs_B = gen_retail_flee_signals()
total_sigs_B = sum(len(v) for v in sigs_B.values())
print(f"  訊號數: {total_sigs_B}")

for sl, ta, ts, mh in [
    (-7.0, 15.0, 10.0, 90),
    (-7.0, 12.0, 8.0, 90),
    (-6.0, 12.0, 7.0, 60),
]:
    m = backtest(sigs_B, price_idx, all_dates, stop_loss=sl,
                 trail_activate=ta, trail_stop=ts, max_hold=mh)
    show(f"B 散戶出逃 SL{sl}% T{ta}%@{ts}% {mh}d", m)


# ══════════════════════════════════════════════════════════════
# 策略 C：大戶高度集中（絕對值）+ 近期上漲
# ratio_400_above > 60% 代表大戶「鎖股」，不是在動態累積
# ══════════════════════════════════════════════════════════════
print("\n  【策略C：大戶高度集中（鎖股）+ 近期上漲】")

def gen_high_concentration_signals():
    sigs = defaultdict(list)
    for code, grp in holdings_df.groupby('stock_code'):
        grp = grp.sort_values('date').reset_index(drop=True)
        if len(grp) < 4 or code not in price_idx:
            continue
        parr = price_idx[code]
        ma20 = ma_idx[code][20]

        for i in range(3, len(grp)):
            r400 = grp['ratio_400_above'].iloc[i]
            if r400 < 60.0:      # 大戶持有 > 60%
                continue

            pi = np.searchsorted(parr[:, 0], grp['date'].iloc[i])
            if pi >= len(parr):
                continue
            cp = float(parr[pi, 1])
            if cp < 100:
                continue

            # 近4週價格上漲（不是鎖死在低點）
            pi_4w = max(0, pi - 20)
            cp_4w = float(parr[pi_4w, 1])
            if cp <= cp_4w:
                continue

            # 站上 MA20
            if np.isnan(ma20[pi]) or cp < ma20[pi]:
                continue

            if pi + 3 < len(parr):
                buy_date = parr[pi+3, 0]
                buy_price = float(parr[pi+3, 1])
                sigs[buy_date].append((code, buy_price))
    return sigs

sigs_C = gen_high_concentration_signals()
total_sigs_C = sum(len(v) for v in sigs_C.values())
print(f"  訊號數: {total_sigs_C}")

for sl, ta, ts, mh in [
    (-7.0, 15.0, 10.0, 90),
    (-7.0, 12.0, 8.0, 90),
    (-6.0, 12.0, 7.0, 60),
]:
    m = backtest(sigs_C, price_idx, all_dates, stop_loss=sl,
                 trail_activate=ta, trail_stop=ts, max_hold=mh)
    show(f"C 大戶鎖股 SL{sl}% T{ta}%@{ts}% {mh}d", m)


# ══════════════════════════════════════════════════════════════
# 策略 D：純價格動能輪動（不用 TDCC）
# 每個月選近 60 天漲幅最大的前 5 檔，持有到下個月換股
# ══════════════════════════════════════════════════════════════
print("\n  【策略D：月度價格動能輪動（不用TDCC資料）】")

def gen_momentum_rotation_signals(top_n=5, lookback=60, min_price=50):
    """每月第一個交易日，買上個月漲最多的前N檔"""
    sigs = defaultdict(list)
    # 找每月第一個交易日
    month_first = {}
    for d in all_dates:
        ym = d[:6]
        if ym not in month_first:
            month_first[ym] = d

    month_firsts = sorted(month_first.values())

    for rebal_date in month_firsts[3:]:   # 前3個月沒有足夠回望
        # 計算所有股票在過去 lookback 天的漲幅
        scores = []
        for code, parr in price_idx.items():
            idx_now = np.searchsorted(parr[:, 0], rebal_date)
            if idx_now >= len(parr):
                continue
            idx_past = max(0, idx_now - lookback)
            cp_now  = float(parr[idx_now, 1])
            cp_past = float(parr[idx_past, 1])
            if cp_past <= 0 or cp_now < min_price:
                continue
            # 排除 ETF (00開頭)
            if code.startswith('00'):
                continue
            ret = (cp_now - cp_past) / cp_past * 100
            scores.append((code, ret, cp_now))

        # 取前 top_n
        scores.sort(key=lambda x: -x[1])
        for code, ret, bp in scores[:top_n]:
            if ret > 5:  # 至少漲了5%才進
                sigs[rebal_date].append((code, bp))

    return sigs

sigs_D = gen_momentum_rotation_signals(top_n=4, lookback=60)
total_sigs_D = sum(len(v) for v in sigs_D.values())
print(f"  訊號數: {total_sigs_D}")

for sl, ta, ts, mh in [
    (-7.0, 15.0, 10.0, 30),   # 月度輪動用短持有
    (-10.0, 20.0, 12.0, 30),
    (-7.0, 15.0, 10.0, 60),
]:
    m = backtest(sigs_D, price_idx, all_dates, stop_loss=sl,
                 trail_activate=ta, trail_stop=ts, max_hold=mh,
                 max_per_week=10)
    show(f"D 動能輪動 top4 SL{sl}% {mh}d", m)


# ══════════════════════════════════════════════════════════════
# 策略 E：RSI 超賣反彈（均值回歸）
# ══════════════════════════════════════════════════════════════
print("\n  【策略E：RSI超賣反彈（均值回歸）】")

def calc_rsi(closes, period=14):
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).values

def gen_rsi_signals(rsi_buy=30, min_price=100, require_ma20=True):
    sigs = defaultdict(list)
    for code, parr in price_idx.items():
        if len(parr) < 30 or code.startswith('00'):
            continue
        closes = parr[:, 1].astype(float)
        rsi = calc_rsi(closes)
        ma20 = ma_idx[code][20]

        for i in range(20, len(parr)-1):
            cp = closes[i]
            if cp < min_price:
                continue
            if np.isnan(rsi[i]) or rsi[i] > rsi_buy:
                continue
            # RSI 超賣後第一次回升
            if i > 0 and not (np.isnan(rsi[i-1]) or rsi[i-1] > rsi[i]):
                continue  # 必須是 RSI 開始反彈
            # 選擇性：要求站上 MA20
            if require_ma20 and (np.isnan(ma20[i]) or cp < ma20[i] * 0.98):
                continue

            buy_date = parr[i+1, 0]
            buy_price = float(parr[i+1, 1])
            sigs[buy_date].append((code, buy_price))
    return sigs

sigs_E = gen_rsi_signals(rsi_buy=30, require_ma20=False)
sigs_E_ma = gen_rsi_signals(rsi_buy=30, require_ma20=True)
print(f"  訊號數(無MA): {sum(len(v) for v in sigs_E.values())}  訊號數(有MA): {sum(len(v) for v in sigs_E_ma.values())}")

for sigs, label in [(sigs_E, "E RSI<30 無MA"), (sigs_E_ma, "E RSI<30 +MA20")]:
    for sl, ta, ts, mh in [(-7.0, 15.0, 10.0, 30), (-7.0, 12.0, 8.0, 30)]:
        m = backtest(sigs, price_idx, all_dates, stop_loss=sl,
                     trail_activate=ta, trail_stop=ts, max_hold=mh)
        show(f"{label} SL{sl}% T{ta}%@{ts}% {mh}d", m)


# ══════════════════════════════════════════════════════════════
# 策略 F：TDCC 大戶累積 + 52週新高確認（原策略進化版）
# ══════════════════════════════════════════════════════════════
print("\n  【策略F：TDCC訊號 + 52週新高確認（要求更嚴）】")
sys.path.insert(0, str(Path(__file__).parent))
from strategy_v6d import StrategyConfig, prepare_data, scan_signals
from analysis_deep import simulate as sim_v6d

holdings_v6 = holdings_df.copy()
cfg = StrategyConfig()
holdings_v6, price_idx_v6, special_flag = prepare_data(holdings_v6, prices_df, cfg)
signals_base = scan_signals(holdings_v6, price_idx_v6, cfg, special_flag)

def filter_near_52w_high(signals, price_idx, threshold=0.95):
    """只保留股價接近52週新高的訊號（代表真的在突破，不是在死貓反彈）"""
    result = []
    for s in signals:
        if s.code not in price_idx:
            continue
        parr = price_idx[s.code]
        idx = np.searchsorted(parr[:, 0], s.buy_date)
        if idx >= len(parr):
            continue
        idx_252 = max(0, idx - 252)
        cp = float(parr[idx, 1])
        high252 = parr[idx_252:idx, 1].astype(float).max() if idx > idx_252 else cp
        # 股價在252日高點的 threshold 以上
        if cp >= high252 * threshold:
            result.append(s)
    return result

for thresh in [0.80, 0.85, 0.90, 0.95]:
    filtered = filter_near_52w_high(signals_base, price_idx_v6, thresh)
    r, c = sim_v6d(filtered, price_idx_v6, prices_df, cfg)
    closed = [t for t in r.trades if t.exit_reason != '未平倉'] if r else []
    wins = [t for t in closed if t.profit > 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    pr = abs(np.mean([t.return_pct for t in wins])/np.mean([t.return_pct for t in [t for t in closed if t.profit<=0]])) if [t for t in closed if t.profit<=0] and wins else 0
    if r:
        print(f"  {'F TDCC + 近52W高>'+str(int(thresh*100))+'%':40s} | {r.total_return_pct:>+7.1f}% | DD {r.max_drawdown_pct:>6.1f}% "
              f"| Calmar {c:>5.2f} | WR {wr:>4.0f}% PR {pr:.1f} | n={len(closed):>3d}  (訊號:{len(filtered)})")


# ══════════════════════════════════════════════════════════════
# 總結
# ══════════════════════════════════════════════════════════════
print()
print("=" * 95)
print("  參考基準（原始 v6d 策略）")
print("=" * 95)
r_base, c_base = sim_v6d(signals_base, price_idx_v6, prices_df, cfg)
if r_base:
    closed = [t for t in r_base.trades if t.exit_reason != '未平倉']
    wins = [t for t in closed if t.profit > 0]
    losses = [t for t in closed if t.profit <= 0]
    wr = len(wins)/len(closed)*100 if closed else 0
    pr = abs(np.mean([t.return_pct for t in wins])/np.mean([t.return_pct for t in losses])) if losses and wins else 0
    print(f"  {'原始v6d（大戶連升）':40s} | {r_base.total_return_pct:>+7.1f}% | DD {r_base.max_drawdown_pct:>6.1f}% "
          f"| Calmar {c_base:>5.2f} | WR {wr:>4.0f}% PR {pr:.1f} | n={len(closed)}")
