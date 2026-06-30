#!/usr/bin/env python3
# 修正版重跑:修掉 BUG-1(A2跨日fwd)、BUG-2(B過夜)、BUG-3(30K對齊08:45)。
# 全部結論重新確認。誠實前提不變:這年指數翻倍,順勢做多本來就賺。
import pandas as pd, numpy as np, datetime as dt

P="/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
df = pd.read_csv(P, parse_dates=["ts"])
df["t"]=df["ts"].dt.time; df["date"]=df["ts"].dt.date
day = df[(df["t"]>=dt.time(8,45))&(df["t"]<=dt.time(13,45))].copy().sort_values("ts").reset_index(drop=True)

# ---- 修 BUG-3:逐日、對齊08:45 切 30分K(每天10根:0845,0915,...,1315) ----
def mins_since_open(ts):
    base = ts.normalize()+pd.Timedelta(hours=8,minutes=45)
    return (ts-base).total_seconds()/60
day["mso"] = day["ts"].apply(mins_since_open)
day["bin30"] = (day["mso"]//30).astype(int)
g = day.groupby(["date","bin30"])
k = pd.DataFrame({
    "ts": g["ts"].first(), "Open": g["Open"].first(), "High": g["High"].max(),
    "Low": g["Low"].min(), "Close": g["Close"].last(), "Vol": g["Volume"].sum(),
}).reset_index().sort_values("ts").reset_index(drop=True)
print(f"[資料] 30分K={len(k)}根  每日根數中位={k.groupby('date').size().median():.0f}(應≈10)  "
      f"期間{k['ts'].min().date()}→{k['ts'].max().date()}")
print(f"       指數 {k['Close'].iloc[0]:.0f}→{k['Close'].iloc[-1]:.0f} ({(k['Close'].iloc[-1]/k['Close'].iloc[0]-1)*100:+.0f}%)")

k["MA20"]=k["Close"].rolling(20).mean(); k["MA40"]=k["Close"].rolling(40).mean()
k["volthr"]=k["Vol"].rolling(80,min_periods=40).quantile(0.90)
k["big"]=k["Vol"]>=k["volthr"]
k["redline"]=np.where(k["big"]&(k["Close"]>k["Open"]),k["Open"],np.nan)
k["blackline"]=np.where(k["big"]&(k["Close"]<k["Open"]),k["Open"],np.nan)
k["redline"]=k["redline"].ffill(); k["blackline"]=k["blackline"].ffill()
k["is_last_of_day"]=k["date"]!=k["date"].shift(-1)   # 當天最後一根

# ================= B. 接子站法(修正版) =================
def run_B(exit_mode, cost_rt, intraday):
    pos=0; entry=0.0; trades=[]
    for i in range(80,len(k)-1):
        row=k.iloc[i]
        if any(pd.isna(row[x]) for x in ["MA20","MA40","redline","blackline"]): continue
        C=row["Close"]; nxt=k.iloc[i+1]
        above=C>row["redline"] and C>row["blackline"] and C>row["MA20"] and C>row["MA40"]
        below=C<row["redline"] and C<row["blackline"] and C<row["MA20"] and C<row["MA40"]
        if exit_mode=="strict":
            lh=C>row["MA20"] and C>row["MA40"] and C>row["redline"]
            sh=C<row["MA20"] and C<row["MA40"] and C<row["blackline"]
        else:
            lh=C>row["MA40"]; sh=C<row["MA40"]
        # 當沖版:當天最後一根強制用收盤平倉、不留倉、不在最後一根進場
        if intraday and row["is_last_of_day"]:
            if pos==1: trades.append((row["ts"],(C-entry)-cost_rt,1)); pos=0
            elif pos==-1: trades.append((row["ts"],(entry-C)-cost_rt,-1)); pos=0
            continue
        if pos==1 and not lh: trades.append((nxt["ts"],(nxt["Open"]-entry)-cost_rt,1)); pos=0
        elif pos==-1 and not sh: trades.append((nxt["ts"],(entry-nxt["Open"])-cost_rt,-1)); pos=0
        if pos==0:
            if above: pos=1; entry=nxt["Open"]
            elif below: pos=-1; entry=nxt["Open"]
    if pos!=0:
        last=k.iloc[-1]; pnl=(last["Close"]-entry-cost_rt) if pos==1 else (entry-last["Close"]-cost_rt)
        trades.append((last["ts"],pnl,pos))
    return pd.DataFrame(trades,columns=["ts","pnl","dir"])

print("\n================ B. 接子站法(修正:對齊30K + 當沖不留倉) ================")
for intraday in [True, False]:
    tag = "當沖(不留倉)" if intraday else "波段(留倉,對照)"
    print(f"\n--- {tag} ---")
    for cost in [3,6]:
        for mode in ["strict","loose"]:
            t=run_B(mode,cost,intraday)
            if len(t)==0: print(f"  [{mode} 成本{cost}] 無交易"); continue
            net=t["pnl"].sum(); n=len(t); win=(t["pnl"]>0).mean()
            lo=t[t["dir"]==1]; sh=t[t["dir"]==-1]
            t["ym"]=pd.to_datetime(t["ts"]).dt.to_period("M"); bym=t.groupby("ym")["pnl"].sum()
            share=bym.max()/net*100 if net>0 else float('nan')
            print(f"  [{mode:6} 成本{cost}] {n}筆 勝率{win*100:.0f}% 淨{net:+.0f}點({net/n:+.1f}/筆) | "
                  f"多{len(lo)}/{lo['pnl'].sum():+.0f} 空{len(sh)}/{sh['pnl'].sum():+.0f} | 最賺月佔{share:.0f}%")

# ================= A2. 大量延續性(修正:fwd限同日) =================
print("\n================ A2. 大量1分K延續性(修正:fwd同日) ================")
d=day.copy()
d["dir"]=np.sign(d["Close"]-d["Open"])
d["fwd15"]=d.groupby("date")["Close"].shift(-15)-d["Close"]   # 同日內
d["fwd30"]=d.groupby("date")["Close"].shift(-30)-d["Close"]
d["volpct"]=d.groupby("date")["Volume"].transform(lambda s: s.rolling(60,min_periods=20).rank(pct=True))
dv=d[(d["t"]>dt.time(8,50))&d["fwd30"].notna()&d["volpct"].notna()].copy()
def cont(sub,label):
    out=[]
    for h in ["fwd15","fwd30"]:
        s=sub[h]*sub["dir"]; hit=(s>0).mean(); amp=(s/sub["Close"]).mean()*100
        out.append(f"{h}同向{hit*100:.1f}%/幅{amp:+.3f}%")
    print(f"  {label:14}({len(sub):5}根) "+"  ".join(out))
cont(dv,"全部(基準)")
for thr,nm in [(0.90,"前10%大量"),(0.99,"前1%大量")]:
    cont(dv[dv["volpct"]>=thr],nm)
print("  判讀:大量同向率明顯>基準且>50%→延續;接近基準或<50%→無延續edge")

# ================= A3. 量門檻(修正:對齊30K) =================
print("\n================ A3. 量門檻百分位(修正後30K) ================")
print("  1分K Vol:", {f"P{p}":int(day["Volume"].quantile(p/100)) for p in [50,90,95,99]})
print("  30分K Vol:", {f"P{p}":int(k["Vol"].quantile(p/100)) for p in [50,90,95,99]})
print("  老師:1分1000口/30分2萬口/3000口=趨勢盤")
