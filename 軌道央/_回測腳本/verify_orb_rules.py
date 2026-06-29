"""驗證: 把現有 ORB 引擎對齊真逐字稿規則, 比較變體敏感度。
不改 repo, import 既有 orbital_yang.orb 的純函數概念, 但因要支援
『可重複進場 / 固定停損』, 在此重寫一個一般化 runner (邏輯與 orb.py 同源)。

真規則差異點 (vs 現有引擎):
  - 停利目標: 第一根法=1滿(50) / 免盯盤=2滿(100)
  - 進場次數: 每日一筆 vs 可重複進場
  - 停損: 第一根對側 vs 固定-20 (免盯盤 5:1)
進場一律『收破』(close-confirmed), 與逐字稿『要收定』一致。
"""
import sys
import pandas as pd, numpy as np

DATA = "/home/tom/stock-verify/taiex-orbital-yang/data/TXF_1min.csv"
SESSION_START, SESSION_END = "08:45", "13:45"
COST_PTS = 1.4  # 滑價1 + 手續費約0.2pt/邊×2, 與記憶慣例一致 (大台1點=NT$200)


def run(df, take_profit, stop_mode="opposite", fixed_stop=20.0, reentry=False):
    """stop_mode: 'opposite'(第一根對側) or 'fixed'(固定 fixed_stop 點)。
    reentry: True=同日可重複進場。回傳 trades list of dict。"""
    trades = []
    for d, g in df.groupby("date"):
        tm = g["ts"].dt.strftime("%H:%M")
        g = g[(tm >= SESSION_START) & (tm <= SESSION_END)].sort_values("ts").reset_index(drop=True)
        if len(g) < 2:
            continue
        ref_high, ref_low = float(g.iloc[0]["High"]), float(g.iloc[0]["Low"])
        pos = None
        for i in range(1, len(g)):
            bar = g.iloc[i]
            h, l, c = float(bar["High"]), float(bar["Low"]), float(bar["Close"])
            if pos is None:
                if c > ref_high:
                    stop = ref_low if stop_mode == "opposite" else c - fixed_stop
                    pos = ["long", c, stop, c + take_profit]
                elif c < ref_low:
                    stop = ref_high if stop_mode == "opposite" else c + fixed_stop
                    pos = ["short", c, stop, c - take_profit]
            else:
                direction, entry, stop, tp = pos
                exit_p = reason = None
                if direction == "long":
                    if l <= stop: exit_p, reason = stop, "stop"
                    elif h >= tp: exit_p, reason = tp, "tp"
                else:
                    if h >= stop: exit_p, reason = stop, "stop"
                    elif l <= tp: exit_p, reason = tp, "tp"
                if reason:
                    pnl = (exit_p - entry) if direction == "long" else (entry - exit_p)
                    trades.append({"date": d, "pnl": pnl, "reason": reason})
                    pos = None
                    if not reentry:
                        break
        if pos is not None:
            direction, entry, stop, tp = pos
            last_c = float(g.iloc[-1]["Close"])
            pnl = (last_c - entry) if direction == "long" else (entry - last_c)
            trades.append({"date": d, "pnl": pnl, "reason": "eod"})
    return trades


def summ(trades):
    if not trades:
        return None
    p = np.array([t["pnl"] for t in trades], float)
    net = p - COST_PTS
    n = len(p)
    wr = (p > 0).mean()
    return dict(n=n, wr=wr, avg=p.mean(), exp_net=net.mean(),
               tot_net=net.sum(), tp=sum(t["reason"]=="tp" for t in trades),
               stop=sum(t["reason"]=="stop" for t in trades),
               eod=sum(t["reason"]=="eod" for t in trades))


def main():
    df = pd.read_csv(DATA)
    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    print(f"資料: {df['date'].min()} ~ {df['date'].max()}, {df['date'].nunique()} 交易日, {len(df)} 根\n")

    variants = [
        ("A 現有baseline (TP50/對側停損/每日一筆)", dict(take_profit=50)),
        ("B TP100=2滿 (其餘同baseline)",          dict(take_profit=100)),
        ("C 可重複進場 (TP50/對側停損)",          dict(take_profit=50, reentry=True)),
        ("D 可重複進場 (TP100/對側停損)",         dict(take_profit=100, reentry=True)),
        ("E 免盯盤5:1 (TP100/固定停損-20/每日一筆)", dict(take_profit=100, stop_mode="fixed", fixed_stop=20)),
        ("F 免盯盤5:1+可重複進場",                dict(take_profit=100, stop_mode="fixed", fixed_stop=20, reentry=True)),
        ("G 第一根法真版 (TP50/固定停損-20/可重複)", dict(take_profit=50, stop_mode="fixed", fixed_stop=20, reentry=True)),
    ]
    print(f"{'變體':<42}{'筆數':>5}{'勝率':>7}{'淨期望':>8}{'淨總點':>9}{'tp/stop/eod':>14}")
    print("-" * 90)
    for name, kw in variants:
        s = summ(run(df, **kw))
        mix = f"{s['tp']}/{s['stop']}/{s['eod']}"
        print(f"{name:<42}{s['n']:>5}{s['wr']*100:>6.1f}%{s['exp_net']:>8.1f}{s['tot_net']:>9.0f}{mix:>14}")
    print(f"\n成本假設: 每筆來回 {COST_PTS} 點 (滑價1+手續費~0.4)。大台1點=NT$200。")
    print("淨期望=每筆淨點數; 淨總點×200=該變體一年一口大台淨損益(NT$)。")


if __name__ == "__main__":
    main()
