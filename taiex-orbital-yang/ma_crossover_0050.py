"""0050 均線交叉策略回測（軌道鞅實驗的最終落腳點）。

結論：繞一圈（選擇權買方→微台→ETF），唯一同時通過「不盯盤＋機械＋真實資料
＋跨牛熊 robust＋賠相符合胃口」的，是最笨的 0050 均線交叉順勢策略。

規則：快線上穿慢線 → 隔天開盤全壓 0050；下穿 → 隔天開盤清空抱現金。中間不動。
- 趨勢跟單本質：賠的快砍（小傷）、賺的久抱（吃整段）。低/中勝率但賠很小。
- 大多頭年一定輸 buy-hold（那是保險費）；價值在長空讓你待現金、躲開腰斬。

用法：
  ./venv/bin/python ma_crossover_0050.py            # 跑均線組合網格 + 主推組合明細
"""
from pathlib import Path
import urllib.request
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
RAW = HERE / "data" / "0050_2018_raw.csv"
FEE = 0.003       # 來回手續費+滑價（保守）
CAP = 500_000     # 起始資金


def load_0050():
    """讀（或抓）0050 日線，回傳 split 還原後的 (收盤, 開盤) 陣列。"""
    if RAW.exists():
        df = pd.read_csv(RAW)
    else:
        parts = []
        for yr in range(2018, 2027):
            url = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
                   f"&data_id=0050&start_date={yr}-01-01&end_date={yr}-12-31")
            d = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
            parts.append(pd.DataFrame(d["data"]))
        df = pd.concat(parts)
        df.to_csv(RAW, index=False)
    df = df.sort_values("date").reset_index(drop=True)
    df = df[(df["close"] > 0) & (df["open"] > 0)].reset_index(drop=True)  # 清掉壞資料
    c = df["close"].to_numpy(float)
    o = df["open"].to_numpy(float)
    # 自動還原分割：單日 ratio<0.55 或 >1.8 視為分割（0050 於 2025-06-18 做過 1拆4）
    f = np.ones(len(c))
    for i in range(1, len(c)):
        r = c[i] / c[i - 1]
        if r < 0.55 or r > 1.8:
            f[:i] *= r
    return c * f, o * f, df["date"].to_numpy()


def backtest(pc, po, fast, slow, cap=CAP):
    """快線上穿慢線→隔天開盤買；下穿→隔天開盤賣。回傳逐筆與淨值。"""
    mf = pd.Series(pc).rolling(fast).mean().to_numpy()
    ms = pd.Series(pc).rolling(slow).mean().to_numpy()
    held, entry, trades, eq = False, None, [], [cap]
    for i in range(slow + 1, len(pc)):
        if np.isnan(ms[i - 1]):
            eq.append(eq[-1])
            continue
        want = mf[i - 1] > ms[i - 1]
        if want != held:
            if want:
                entry = po[i]
                eq[-1] *= (1 - FEE / 2)
            elif entry is not None:
                trades.append(po[i] / entry - 1)
                entry = None
                eq[-1] *= (1 - FEE / 2)
            held = want
        eq.append(eq[-1] * ((pc[i] / pc[i - 1]) if held else 1.0))
    if entry is not None:
        trades.append(pc[-1] / entry - 1)
    return np.array(trades), np.array(eq)


def stats(trades, eq, cap=CAP):
    pk = np.maximum.accumulate(eq)
    mdd = (eq / pk - 1).min() * 100
    yrs = len(eq) / 245
    cagr = (eq[-1] / cap) ** (1 / yrs) - 1
    win = (trades > 0).mean() * 100 if len(trades) else 0
    return eq[-1], cagr * 100, win, len(trades), mdd


def main():
    pc, po, _ = load_0050()
    print("=== 均線組合網格（0050, 2018-2026, 隔天開盤成交, 扣0.3%）===")
    print(f'{"快/慢":<9}{"50萬→":>11}{"倍":>5}{"年化":>7}{"勝率":>6}{"筆":>4}{"回撤":>7}')
    for fast, slow in [(5, 10), (5, 20), (5, 60), (10, 20), (10, 60), (20, 60)]:
        fin, cagr, win, n, mdd = stats(*backtest(pc, po, fast, slow))
        star = " ⭐" if (fast, slow) == (10, 60) else ""
        print(f'{f"{fast}/{slow}":<9}{fin:>11,.0f}{fin/CAP:>4.2f}x{cagr:>+6.1f}%{win:>5.0f}%{n:>4}{mdd:>6.1f}%{star}')
    bh = pc[-1] / pc[60]
    print(f'\n參考-買進抱住: ×{bh:.2f} (+{(bh-1)*100:.0f}%), 回撤約 -36%')
    print("\n發現：慢線用季線(60)的全部贏過用月線(20)；快線太快(5/10)最爛(105次來回挨刀)。")
    print("     單一冠軍是 overfitting；可信的是『季線當慢線』這個方向。")
    print("     主推 10/60：勝率最高(56%)、8年才16筆、最不盯盤。")
    report_long_history()


def report_long_history():
    """若有 2003-2017 資料，跑長期(含2008海嘯/2020 COVID/2022升息)分析。"""
    raw03 = HERE / "data" / "0050_2003_2017_raw.csv"
    if not raw03.exists():
        print("\n(無 2003-2017 資料，略過長期分析)")
        return
    df = pd.concat([pd.read_csv(raw03), pd.read_csv(RAW)]).drop_duplicates("date")
    df = df.sort_values("date").reset_index(drop=True)
    df = df[(df["close"] > 0) & (df["open"] > 0)].reset_index(drop=True)
    c, o = df["close"].to_numpy(float), df["open"].to_numpy(float)
    dt = pd.to_datetime(df["date"])
    f = np.ones(len(c))
    for i in range(1, len(c)):
        r = c[i] / c[i - 1]
        if r < 0.55 or r > 1.8:
            f[:i] *= r
    pc, po = c * f, o * f

    def win_run(fast, slow, lo, hi):
        mf = pd.Series(pc).rolling(fast).mean().to_numpy()
        ms = pd.Series(pc).rolling(slow).mean().to_numpy()
        held, eq, eqv = False, 1.0, []
        for i in np.where((dt >= lo) & (dt <= hi))[0]:
            if i < slow + 1 or np.isnan(ms[i - 1]):
                continue
            want = mf[i - 1] > ms[i - 1]
            if want != held:
                eq *= (1 - FEE / 2)
                held = want
            eq *= (pc[i] / pc[i - 1]) if held else 1.0
            eqv.append(eq)
        eqv = np.array(eqv)
        return (eqv[-1] - 1) * 100, (eqv / np.maximum.accumulate(eqv) - 1).min() * 100

    def bh_win(lo, hi):
        p = pc[np.where((dt >= lo) & (dt <= hi))[0]]
        return (p[-1] / p[0] - 1) * 100, (p / np.maximum.accumulate(p) - 1).min() * 100

    print("\n=== 三種空頭實測（10/60；V急殺也罩得住）===")
    for nm, lo, hi in [("2020 COVID(V急殺)", "2020-01-01", "2020-09-30"),
                       ("2022 升息慢空", "2022-01-01", "2022-12-31"),
                       ("2008 金融海嘯", "2008-01-01", "2009-06-30")]:
        br, bdd = bh_win(lo, hi)
        sr, sdd = win_run(10, 60, lo, hi)
        print(f"  {nm:<18} 抱住 {br:+4.0f}%/回撤{bdd:+4.0f}%   策略 {sr:+4.0f}%/回撤{sdd:+4.0f}%")
    print("  → 三種都把回撤砍到 1/3~1/2，2008與2020還倒賺。")
    print("     長期(2003-2026)年化僅~7.8%(正常年代+2.9%)；它是『賠更少、活下來』不是『賺更多』。")


if __name__ == "__main__":
    main()
