"""買方專用回測: 進場後『抱著、台指期到大目標就賣(option賣在噴點)、沒到就收盤砍』。

買方風險封頂=權利金, 不設中途停損。掃不同『賣點目標(點數)』看哪個買方最好。
進場 = 順格局 ORB(站上8:46高買CALL/破低買PUT)。真實 TXO 權利金。
"""
from pathlib import Path
import numpy as np
import pandas as pd

from orbital_yang.data_loader import load_daily
from orbital_yang.regime import alignment_sign
from orbital_yang.orb_options import option_ohlc, buyer_pnl
from orbital_yang.txo_data import fetch_chain, pick_entry_option

HERE = Path(__file__).parent
HS, CO, PV = 1.0, 20.0, 50.0
DATE_FLOOR = "2025-12-13"
TARGETS = [50, 100, 150, 200]
SS, SE = "08:45", "13:45"


def signals(daily, m):
    """回傳每個順格局日的 (date, kind, ref_high, ref_low, day_df)。"""
    sign = alignment_sign(daily, 20, 60)
    dd = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d").to_numpy()
    reg = {dd[i]: int(sign[i]) for i in range(len(dd)) if sign[i] != 0}
    m = m.copy(); m["ts"] = pd.to_datetime(m["ts"])
    m["d"] = m["ts"].dt.strftime("%Y-%m-%d"); m["t"] = m["ts"].dt.strftime("%H:%M")
    out = []
    for d, g in m.groupby("d"):
        r = reg.get(d, 0)
        if r == 0 or d < DATE_FLOOR:
            continue
        sess = g[(g["t"] >= SS) & (g["t"] <= SE)].sort_values("ts").reset_index(drop=True)
        if len(sess) < 3:
            continue
        out.append((d, "call" if r == 1 else "put", float(sess.iloc[0]["High"]),
                    float(sess.iloc[0]["Low"]), sess, r))
    return out


def main():
    daily = load_daily(str(HERE / "data" / "TXF_daily.csv"))
    m = pd.read_csv(HERE / "data" / "TXF_1min.csv")
    sigs = signals(daily, m)

    print("=" * 60)
    print(" 買方賣點目標掃描 (進場=順格局ORB; 抱到目標賣/沒到收盤砍; 無停損)")
    print("=" * 60)
    print(f" {'賣點目標':>8}{'有進場':>7}{'勝率':>6}{'到目標%':>8}{'ROI':>7}{'總損益':>10}{'2x率':>6}")
    for N in TARGETS:
        rows = []
        for d, kind, rh, rl, sess, r in sigs:
            H = sess["High"].to_numpy(float); L = sess["Low"].to_numpy(float); C = sess["Close"].to_numpy(float)
            n = len(sess)
            ei = None
            for i in range(1, n):
                if (r == 1 and C[i] > rh) or (r == -1 and C[i] < rl):
                    ei = i; break
            if ei is None:
                continue
            trig = rh if r == 1 else rl
            # 指數進場後最大有利噴幅 M
            if r == 1:
                M = float(np.max(H[ei + 1:])) - trig
            else:
                M = trig - float(np.min(L[ei + 1:]))
            try:
                ch = fetch_chain(d); opt = pick_entry_option(ch, kind, 30.0)
                oh = option_ohlc(ch, opt["contract_date"], opt["strike_price"], kind) if opt else None
                if not oh or oh["open"] <= 0:
                    continue
            except Exception:
                continue
            if M >= N and M > 0:       # 指數有噴到 +N -> 在那點賣 (option值線性內插, 非賣在最高)
                ex = oh["open"] + (oh["high"] - oh["open"]) * (N / M)
                hit = True
            else:                       # 沒噴到 +N -> 收盤砍
                ex = oh["close"]; hit = False
            rows.append({"pnl": buyer_pnl(oh["open"], ex, HS, CO, PV), "prem": oh["open"],
                         "hit": hit, "mult": ex / oh["open"]})
        if not rows:
            print(f" {N:>8} 0"); continue
        pnl = np.array([x["pnl"] for x in rows]); prem = np.mean([x["prem"] for x in rows])
        mult = np.array([x["mult"] for x in rows]); hitr = np.mean([x["hit"] for x in rows])
        print(f" {N:>6}點{len(rows):>7}{(pnl>0).mean():>6.0%}{hitr:>8.0%}"
              f"{pnl.mean()/prem:>+7.0%}{pnl.sum()*PV:>+10,.0f}{(mult>=2).mean():>6.0%}")
    print("\n (賣=到目標賣當日高/沒到賣收盤; 風險封頂=權利金; 近半年真實TXO)")


if __name__ == "__main__":
    main()
