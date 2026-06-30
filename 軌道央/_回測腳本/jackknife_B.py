#!/usr/bin/env python3
# Jackknife:把接子站法「當沖忠實版」逐月P&L攤開,拿掉最賺月看還剩多少 → 釘死脆弱性。
import pandas as pd, numpy as np, datetime as dt
P="/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
df=pd.read_csv(P,parse_dates=["ts"]); df["t"]=df["ts"].dt.time; df["date"]=df["ts"].dt.date
day=df[(df["t"]>=dt.time(8,45))&(df["t"]<=dt.time(13,45))].copy().sort_values("ts").reset_index(drop=True)
def mso(ts): return (ts-(ts.normalize()+pd.Timedelta(hours=8,minutes=45))).total_seconds()/60
day["bin30"]=(day["ts"].apply(mso)//30).astype(int)
g=day.groupby(["date","bin30"])
k=pd.DataFrame({"ts":g["ts"].first(),"Open":g["Open"].first(),"Close":g["Close"].last(),"Vol":g["Volume"].sum()}).reset_index().sort_values("ts").reset_index(drop=True)
k["MA20"]=k["Close"].rolling(20).mean();k["MA40"]=k["Close"].rolling(40).mean()
k["volthr"]=k["Vol"].rolling(80,min_periods=40).quantile(0.90);k["big"]=k["Vol"]>=k["volthr"]
k["redline"]=np.where(k["big"]&(k["Close"]>k["Open"]),k["Open"],np.nan)
k["blackline"]=np.where(k["big"]&(k["Close"]<k["Open"]),k["Open"],np.nan)
k["redline"]=k["redline"].ffill();k["blackline"]=k["blackline"].ffill()
k["last"]=k["date"]!=k["date"].shift(-1)
def run(mode,cost):
    pos=0;entry=0;tr=[]
    for i in range(80,len(k)-1):
        r=k.iloc[i]
        if any(pd.isna(r[x]) for x in ["MA20","MA40","redline","blackline"]):continue
        C=r["Close"];nx=k.iloc[i+1]
        ab=C>r["redline"]and C>r["blackline"]and C>r["MA20"]and C>r["MA40"]
        be=C<r["redline"]and C<r["blackline"]and C<r["MA20"]and C<r["MA40"]
        lh=(C>r["MA20"]and C>r["MA40"]and C>r["redline"])if mode=="strict"else C>r["MA40"]
        sh=(C<r["MA20"]and C<r["MA40"]and C<r["blackline"])if mode=="strict"else C<r["MA40"]
        if r["last"]:
            if pos==1:tr.append((r["ts"],C-entry-cost,1));pos=0
            elif pos==-1:tr.append((r["ts"],entry-C-cost,-1));pos=0
            continue
        if pos==1 and not lh:tr.append((nx["ts"],nx["Open"]-entry-cost,1));pos=0
        elif pos==-1 and not sh:tr.append((nx["ts"],entry-nx["Open"]-cost,-1));pos=0
        if pos==0:
            if ab:pos=1;entry=nx["Open"]
            elif be:pos=-1;entry=nx["Open"]
    return pd.DataFrame(tr,columns=["ts","pnl","dir"])
for mode in ["strict","loose"]:
    t=run(mode,6)  # 成本6點(較真實)
    t["ym"]=pd.to_datetime(t["ts"]).dt.to_period("M");bym=t.groupby("ym")["pnl"].sum().sort_index()
    net=t["pnl"].sum()
    print(f"\n=== 當沖 {mode} 成本6 ===  全年淨 {net:+.0f}點 ({len(t)}筆)")
    print("  逐月:", "  ".join(f"{str(m)[2:]}:{v:+.0f}" for m,v in bym.items()))
    best=bym.idxmax();worst=bym.idxmin()
    print(f"  最賺月 {best} {bym.max():+.0f} | 最賠月 {worst} {bym.min():+.0f}")
    print(f"  拿掉最賺月 → {net-bym.max():+.0f}點 | 再拿掉次賺月 → {net-bym.nlargest(2).sum():+.0f}點")
    print(f"  正月數 {(bym>0).sum()}/{len(bym)}  → {'過半正' if (bym>0).mean()>0.5 else '正月未過半'}")
