"""選擇性進場回測 (老師真打法) vs 每根第一根突破。

機制 (依逐字稿免盯盤 + 三法/呂布):
  - 粗量K = 當日盤中成交量 > 前 n 根 median × k  (粗量=成交量, 非實體!)
  - 粗量紅K(收>開) -> 紅底(support) = 開盤價; 粗量黑K -> 黑頂(resistance) = 開盤價
  - 進場 = 回測關卡(掛單在關卡價, 觸價成交), 不是在粗量K當下追
  - 停損 -20, 停利 +100 (免盯盤 5:1); 另測 +50(1滿)
  - 關卡盤中有效, EOD 以最後收盤平倉
  - regime: 順日線 MA20/60 當前方向 (只做順勢邊) 可開關
備註(暫無法編碼, 待音檔補): 起始攻擊量 vs 出貨量區分(跑完滿足點不接)、呂布第一/二隻腳精確timing。
"""
import sys, pandas as pd, numpy as np
sys.path.insert(0, "/home/tom/stock-verify/taiex-orbital-yang")
from orbital_yang.regime import alignment_sign

DATA = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
DAILY = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_daily.csv"
SESSION_START, SESSION_END = "08:45", "13:45"
COST_PTS = 1.4


def daily_sign_map(fast=20, slow=60):
    d = pd.read_csv(DAILY)
    # 容錯欄名
    cols = {c.lower(): c for c in d.columns}
    d = d.rename(columns={cols.get("date","date"):"date", cols.get("close","close"):"close"})
    d["date"] = pd.to_datetime(d["date"])
    sign = alignment_sign(d[["close"]], fast, slow)
    return dict(zip(d["date"].dt.strftime("%Y-%m-%d"), sign))


def run_selective(df, k, n, tp=100.0, stop=20.0, regime=None, signmap=None):
    """regime: None=不過濾 / 'trend'=只做順日線MA20/60當前方向邊。"""
    trades = []
    for d, g in df.groupby("date"):
        tm = g["ts"].dt.strftime("%H:%M")
        g = g[(tm >= SESSION_START) & (tm <= SESSION_END)].sort_values("ts").reset_index(drop=True)
        if len(g) < n + 2:
            continue
        vol = g["Volume"].to_numpy(float)
        med = pd.Series(vol).shift(1).rolling(n).median().to_numpy()
        o = g["Open"].to_numpy(float); c = g["Close"].to_numpy(float)
        h = g["High"].to_numpy(float); l = g["Low"].to_numpy(float)
        allow = signmap.get(str(d)) if (regime == "trend" and signmap) else None  # +1/-1/0/None
        supports, resistances = [], []   # 已武裝的掛單關卡價
        pos = None                       # (dir, entry, stop_p, tp_p)
        for i in range(len(g)):
            if pos is None:
                # 檢查觸價成交 (回測關卡)
                hit = None
                cand_s = [S for S in supports if l[i] <= S]   # 跌到支撐 -> 多單掛單成交
                cand_r = [R for R in resistances if h[i] >= R]
                if cand_s and (allow is None or allow > 0):
                    S = max(cand_s); hit = ("long", S, S - stop, S + tp); supports.remove(S)
                elif cand_r and (allow is None or allow < 0):
                    R = min(cand_r); hit = ("short", R, R + stop, R - tp); resistances.remove(R)
                if hit:
                    # 同根就可能掃損/停利: 保守先判停損
                    dr, e, st, tpp = hit
                    if dr == "long":
                        if l[i] <= st: trades.append({"date":d,"dir":dr,"pnl":st-e,"reason":"stop"})
                        elif h[i] >= tpp: trades.append({"date":d,"dir":dr,"pnl":tpp-e,"reason":"tp"})
                        else: pos = hit
                    else:
                        if h[i] >= st: trades.append({"date":d,"dir":dr,"pnl":st-e,"reason":"stop"})
                        elif l[i] <= tpp: trades.append({"date":d,"dir":dr,"pnl":tpp-e,"reason":"tp"})
                        else: pos = hit
            else:
                dr, e, st, tpp = pos; xp = rs = None
                if dr == "long":
                    if l[i] <= st: xp, rs = st, "stop"
                    elif h[i] >= tpp: xp, rs = tpp, "tp"
                else:
                    if h[i] >= st: xp, rs = st, "stop"
                    elif l[i] <= tpp: xp, rs = tpp, "tp"
                if rs:
                    pnl = (xp - e) if dr == "long" else (e - xp)
                    trades.append({"date":d,"dir":dr,"pnl":pnl,"reason":rs}); pos = None
            # 註冊本根新關卡 (供之後的根回測)
            big = (med[i] == med[i]) and vol[i] > med[i] * k
            if big:
                if c[i] > o[i]: supports.append(o[i])
                elif c[i] < o[i]: resistances.append(o[i])
        if pos is not None:
            dr, e, st, tpp = pos; lc = c[-1]
            trades.append({"date":d,"dir":dr,"pnl":(lc-e) if dr=="long" else (e-lc),"reason":"eod"})
    return trades


def summ(trades):
    if not trades: return dict(n=0, wr=0, exp=0, tot=0, mix="0/0/0")
    p = np.array([t["pnl"] for t in trades], float); net = p - COST_PTS
    return dict(n=len(p), wr=(p>0).mean()*100, exp=net.mean(), tot=net.sum(),
               mix=f"{sum(t['reason']=='tp' for t in trades)}/{sum(t['reason']=='stop' for t in trades)}/{sum(t['reason']=='eod' for t in trades)}")


def main():
    df = pd.read_csv(DATA); df["ts"] = pd.to_datetime(df["ts"]); df["date"] = df["ts"].dt.date
    sm = daily_sign_map()
    print(f"資料 {df['date'].min()}~{df['date'].max()}, {df['date'].nunique()} 日。成本 {COST_PTS}點/筆。\n")
    print("選擇性進場 = 粗量K(成交量)成關卡 -> 回測掛單成交 -> 停損-20/停利+100(5:1)\n")
    hdr = f"{'設定':<46}{'筆數':>5}{'勝率':>7}{'淨期望':>8}{'淨總點':>9}{'tp/st/eod':>12}"
    print(hdr); print("-"*88)
    rows = [
        ("粗量2×/窗60/無過濾",            dict(k=2, n=60)),
        ("粗量3×/窗60/無過濾",            dict(k=3, n=60)),
        ("粗量4×/窗60/無過濾",            dict(k=4, n=60)),
        ("粗量2×/窗30/無過濾",            dict(k=2, n=30)),
        ("粗量3×/窗60/順格局過濾",        dict(k=3, n=60, regime="trend", signmap=sm)),
        ("粗量4×/窗60/順格局過濾",        dict(k=4, n=60, regime="trend", signmap=sm)),
        ("粗量3×/窗60/TP50(1滿)",        dict(k=3, n=60, tp=50)),
        ("粗量3×/窗60/順格局+TP50",       dict(k=3, n=60, tp=50, regime="trend", signmap=sm)),
    ]
    for name, kw in rows:
        s = summ(run_selective(df, **kw))
        print(f"{name:<46}{s['n']:>5}{s['wr']:>6.1f}%{s['exp']:>8.1f}{s['tot']:>9.0f}{s['mix']:>12}")
    print("\n對照組(昨天): 每根第一根突破 TP100/對側停損/每日一筆 = 257筆 / 48.2% / +10.5 / +2690")


if __name__ == "__main__":
    main()
