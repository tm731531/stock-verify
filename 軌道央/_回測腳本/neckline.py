"""頸線系統回測 (一線判多空)。

頸線 = 水平歷史 S/R = swing pivot 價位 (過前高回測不破 / 破前低反彈不過)。
打法 (breakout-retest, 過→回測不破→續攻):
  - 收盤『過』壓力頸線R + 大量 -> R 變支撐, 武裝多單
  - 之後某根回測該破線(Low<=R) 且實體收回上方(Close>R) -> 觸架做多
  - 停損 = 破線(後續收破), 停利 = 上方下一條頸線(沒有則用測幅)
  - 對稱做空
avoid look-ahead: pivot 在 i, 需 i+w 根後才確認, 之後才可用。
級數: 1分K resample 30分K (台指 8:46-13:45 約10根/日)。
"""
import sys, pandas as pd, numpy as np
DATA = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
COST_PTS = 1.4


def resample(df, rule="30min"):
    s = df.set_index("ts")
    o = s["Open"].resample(rule).first()
    h = s["High"].resample(rule).max()
    l = s["Low"].resample(rule).min()
    c = s["Close"].resample(rule).last()
    v = s["Volume"].resample(rule).sum()
    r = pd.DataFrame({"Open":o,"High":h,"Low":l,"Close":c,"Volume":v}).dropna()
    return r.reset_index()


def pivots(h, l, w):
    """回傳 (res_idx_set, sup_idx_set): pivot high/low 的索引。"""
    res, sup = [], []
    for i in range(w, len(h)-w):
        if h[i] == max(h[i-w:i+w+1]): res.append(i)
        if l[i] == min(l[i-w:i+w+1]): sup.append(i)
    return res, sup


def run_neckline(df30, w=3, volk=1.3, stopbuf=0.0, tp_mode="next", mm=50, vol_win=20):
    h = df30["High"].to_numpy(float); l = df30["Low"].to_numpy(float)
    o = df30["Open"].to_numpy(float); c = df30["Close"].to_numpy(float)
    v = df30["Volume"].to_numpy(float)
    vma = pd.Series(v).shift(1).rolling(vol_win).mean().to_numpy()
    res_idx, sup_idx = pivots(h, l, w)
    res_conf = {i+w: h[i] for i in res_idx}   # 確認bar -> 價
    sup_conf = {i+w: l[i] for i in sup_idx}
    res_levels, sup_levels = [], []            # 已確認可用的頸線價
    armed_long, armed_short = [], []           # 突破後武裝的(原R變支撐 / 原S變壓力)
    trades = []; pos = None
    for i in range(len(df30)):
        if i in res_conf: res_levels.append(res_conf[i])
        if i in sup_conf: sup_levels.append(sup_conf[i])
        big = vma[i] == vma[i] and v[i] > vma[i]*volk
        # 出場
        if pos is not None:
            dr,e,lvl,tp = pos; xp=rs=None
            if dr=="long":
                if c[i] < lvl: xp,rs=c[i],"stop"
                elif h[i] >= tp: xp,rs=tp,"tp"
            else:
                if c[i] > lvl: xp,rs=c[i],"stop"
                elif l[i] <= tp: xp,rs=tp,"tp"
            if rs:
                trades.append({"ts":df30["ts"].iloc[i],"dir":dr,"pnl":(xp-e) if dr=="long" else (e-xp),"reason":rs}); pos=None
        # 突破武裝: 收盤過壓力頸線+大量 -> 變支撐武裝多
        if big:
            for R in [x for x in res_levels if c[i] > x and o[i] <= x*1.002]:
                armed_long.append(R)
            for S in [x for x in sup_levels if c[i] < x and o[i] >= x*0.998]:
                armed_short.append(S)
        # 進場: 回測觸架
        if pos is None:
            hitL = [R for R in armed_long if l[i] <= R and c[i] > R]
            hitS = [S for S in armed_short if h[i] >= S and c[i] < S]
            if hitL:
                R = max(hitL); ups = [x for x in res_levels if x > c[i]]
                tp = min(ups) if (tp_mode=="next" and ups) else c[i]+mm
                pos = ("long", c[i], R-stopbuf, tp); armed_long.remove(R)
            elif hitS:
                S = min(hitS); dns = [x for x in sup_levels if x < c[i]]
                tp = max(dns) if (tp_mode=="next" and dns) else c[i]-mm
                pos = ("short", c[i], S+stopbuf, tp); armed_short.remove(S)
        # 失效清理(可選): 已被反向實體穿破的武裝移除
        armed_long = [R for R in armed_long if not c[i] < R*0.99]
        armed_short = [S for S in armed_short if not c[i] > S*1.01]
    return trades


def summ(ts):
    if not ts: return dict(n=0,wr=0,exp=0,tot=0,mix="0/0")
    p=np.array([t["pnl"] for t in ts],float); net=p-COST_PTS
    return dict(n=len(p),wr=(p>0).mean()*100,exp=net.mean(),tot=net.sum(),
        mix=f"{sum(t['reason']=='tp' for t in ts)}/{sum(t['reason']=='stop' for t in ts)}")


def main():
    df = pd.read_csv(DATA); df["ts"]=pd.to_datetime(df["ts"])
    for rule in ["30min","60min"]:
        d = resample(df, rule)
        print(f"\n===== 級數 {rule} ({len(d)}根) =====")
        print(f"{'設定':<40}{'筆數':>5}{'勝率':>7}{'淨期望':>8}{'淨總':>9}{'tp/stop':>10}")
        print("-"*80)
        for name,kw in [
          ("pivot w3 / 量1.3x / 停利下條頸線", dict(w=3,volk=1.3,tp_mode="next")),
          ("pivot w3 / 量1.3x / 停利測幅50",   dict(w=3,volk=1.3,tp_mode="mm",mm=50)),
          ("pivot w3 / 量1.3x / 停利測幅150",  dict(w=3,volk=1.3,tp_mode="mm",mm=150)),
          ("pivot w5 / 量1.3x / 停利下條頸線", dict(w=5,volk=1.3,tp_mode="next")),
          ("pivot w5 / 量1.5x / 停利下條頸線", dict(w=5,volk=1.5,tp_mode="next")),
          ("pivot w3 / 量1.0x(不濾量) / 下條",  dict(w=3,volk=0.0,tp_mode="next")),
        ]:
            s=summ(run_neckline(d,**kw))
            print(f"{name:<40}{s['n']:>5}{s['wr']:>6.1f}%{s['exp']:>8.1f}{s['tot']:>9.0f}{s['mix']:>10}")
    print("\n對照: 第一根突破 TP100/每日一筆 = 257筆/48%/+10.5/+2690")


if __name__ == "__main__":
    main()
