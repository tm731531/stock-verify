"""選擇性進場 v2 — 加入三法奧義的選擇性過濾器。

vs v1(全負)的關鍵差異:
  1. 觸架確認(非掛單觸價): 進場要求測試K「實體收回正確側」
     - support: 該根 Low<=關卡 (影線測到) 且 Close>關卡 (收回上方) -> 觸架, 做多
     - 若 Close<關卡 (實體灌破=穿架) -> 關卡失效, 移除, 不進反而該防
  2. AM盤時間窗: 只在 <=cutoff(預設10:00) 進場 (10點後沒亮)
  3. 停損=實體破關卡(後續K收破), 停利=+target
  4. 每日兩敗收手 (可選)
粗量=成交量 > 前n根median × k。買黑不買紅(回射進場本質=黑K測支撐)。
"""
import sys, pandas as pd, numpy as np
sys.path.insert(0, "/home/tom/stock-verify/taiex-orbital-yang")
from orbital_yang.regime import alignment_sign

DATA = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
DAILY = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_daily.csv"
SESSION_START, SESSION_END = "08:45", "13:45"
COST_PTS = 1.4


def daily_sign_map(fast=20, slow=60):
    d = pd.read_csv(DAILY); cols = {c.lower(): c for c in d.columns}
    d = d.rename(columns={cols.get("date","date"):"date", cols.get("close","close"):"close"})
    d["date"] = pd.to_datetime(d["date"])
    return dict(zip(d["date"].dt.strftime("%Y-%m-%d"), alignment_sign(d[["close"]], fast, slow)))


def run_v2(df, k=3, n=60, target=50.0, cutoff="10:00", two_loss=False,
           regime=None, signmap=None, require_confirm=True):
    trades = []
    for d, g in df.groupby("date"):
        tms = g["ts"].dt.strftime("%H:%M")
        g = g[(tms >= SESSION_START) & (tms <= SESSION_END)].sort_values("ts").reset_index(drop=True)
        if len(g) < n + 2: continue
        t = g["ts"].dt.strftime("%H:%M").to_numpy()
        vol = g["Volume"].to_numpy(float)
        med = pd.Series(vol).shift(1).rolling(n).median().to_numpy()
        o,c,h,l = (g[x].to_numpy(float) for x in ["Open","Close","High","Low"])
        allow = signmap.get(str(d)) if (regime == "trend" and signmap) else None
        supports, resistances = [], []
        pos = None; losses = 0
        for i in range(len(g)):
            # --- 出場 ---
            if pos is not None:
                dr, e, lvl, tp = pos; xp = rs = None
                if dr == "long":
                    if c[i] < lvl: xp, rs = c[i], "stop"      # 實體收破關卡=穿價失效
                    elif h[i] >= tp: xp, rs = tp, "tp"
                else:
                    if c[i] > lvl: xp, rs = c[i], "stop"
                    elif l[i] <= tp: xp, rs = tp, "tp"
                if rs:
                    pnl = (xp-e) if dr=="long" else (e-xp)
                    trades.append({"date":d,"dir":dr,"pnl":pnl,"reason":rs})
                    pos = None
                    if pnl <= 0: losses += 1
            # --- 進場 (觸架確認) ---
            if pos is None and t[i] <= cutoff and not (two_loss and losses >= 2):
                # support: 影線測到、實體收回上方
                hitS = [S for S in supports if l[i] <= S and (c[i] > S if require_confirm else True)]
                hitR = [R for R in resistances if h[i] >= R and (c[i] < R if require_confirm else True)]
                if hitS and (allow is None or allow > 0):
                    S = max(hitS); pos = ("long", c[i], S, c[i] + target); supports.remove(S)
                elif hitR and (allow is None or allow < 0):
                    R = min(hitR); pos = ("short", c[i], R, c[i] - target); resistances.remove(R)
            # --- 穿架失效: 實體灌破的關卡移除 ---
            supports = [S for S in supports if not (c[i] < S)]
            resistances = [R for R in resistances if not (c[i] > R)]
            # --- 註冊新粗量關卡 ---
            if med[i] == med[i] and vol[i] > med[i] * k:
                if c[i] > o[i]: supports.append(o[i])
                elif c[i] < o[i]: resistances.append(o[i])
        if pos is not None:
            dr, e, lvl, tp = pos
            trades.append({"date":d,"dir":dr,"pnl":(c[-1]-e) if dr=="long" else (e-c[-1]),"reason":"eod"})
    return trades


def summ(ts):
    if not ts: return dict(n=0,wr=0,exp=0,tot=0,mix="0/0/0")
    p = np.array([t["pnl"] for t in ts], float); net = p - COST_PTS
    return dict(n=len(p), wr=(p>0).mean()*100, exp=net.mean(), tot=net.sum(),
        mix=f"{sum(t['reason']=='tp' for t in ts)}/{sum(t['reason']=='stop' for t in ts)}/{sum(t['reason']=='eod' for t in ts)}")


def main():
    df = pd.read_csv(DATA); df["ts"]=pd.to_datetime(df["ts"]); df["date"]=df["ts"].dt.date
    sm = daily_sign_map()
    print(f"資料 {df['date'].min()}~{df['date'].max()}, {df['date'].nunique()}日。成本{COST_PTS}/筆。")
    print("v2 = 觸架確認(實體收回)+ AM盤窗 + 穿架失效移除\n")
    print(f"{'設定':<48}{'筆數':>5}{'勝率':>7}{'淨期望':>8}{'淨總':>9}{'tp/st/eod':>12}")
    print("-"*90)
    rows = [
      ("v1對照: 無觸架/整天/掛單觸價 (TP50)",  dict(target=50, cutoff="13:45", require_confirm=False)),
      ("v2: 觸架+整天 (TP50)",                dict(target=50, cutoff="13:45")),
      ("v2: 觸架+AM窗10點 (TP50)",            dict(target=50, cutoff="10:00")),
      ("v2: 觸架+AM窗10點 (TP140 比例化)",     dict(target=140, cutoff="10:00")),
      ("v2: 觸架+AM窗+兩敗收手 (TP50)",        dict(target=50, cutoff="10:00", two_loss=True)),
      ("v2: 觸架+AM窗+順格局 (TP50)",          dict(target=50, cutoff="10:00", regime="trend", signmap=sm)),
      ("v2: 觸架+AM窗9:30 (TP50)",            dict(target=50, cutoff="09:30")),
      ("v2: 觸架+AM窗10點 粗量4× (TP50)",      dict(target=50, cutoff="10:00", k=4)),
    ]
    for name, kw in rows:
        s = summ(run_v2(df, **kw))
        print(f"{name:<48}{s['n']:>5}{s['wr']:>6.1f}%{s['exp']:>8.1f}{s['tot']:>9.0f}{s['mix']:>12}")
    print("\n對照: 第一根突破 TP100/每日一筆 = 257筆/48%/+10.5/+2690")


if __name__ == "__main__":
    main()
