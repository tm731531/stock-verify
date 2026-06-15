"""B3: 大小流氓(月季線)過濾 + 真實 TXO 權利金, 比對 EOD 買方能不能成。

回答 Tom 的核心疑問: 一天看一次能不能賺, 還是非得盤中盯。
"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest, summarize
from orbital_yang.option_buyer import OptionTrade, summarize_options
from orbital_yang.txo_data import fetch_chain, pick_entry_option, lookup_premium

DATA = Path(__file__).parent / "data" / "TXF_daily.csv"
OUT = Path(__file__).parent / "reports" / "b3_full.md"
N, K = 20, 1.5
TM, MH = 2.0, 20
TARGET_PREMIUM, HOLD_CAP = 30.0, 3
DATE_FLOOR = "2025-06-01"


def real_opts(df, dates, trades):
    out, skipped = [], 0
    for tr in trades:
        if dates[tr.entry_idx] < DATE_FLOOR:
            continue
        kind = "call" if tr.direction == "long" else "put"
        ed = dates[tr.entry_idx]
        xi = min(tr.exit_idx, tr.entry_idx + HOLD_CAP)
        xd = dates[xi]
        try:
            opt = pick_entry_option(fetch_chain(ed), kind, TARGET_PREMIUM)
            if opt is None:
                skipped += 1; continue
            xp = lookup_premium(fetch_chain(xd), opt["contract_date"], opt["strike_price"], kind)
        except Exception as e:
            print(f"  {ed} 失敗 {e}"); skipped += 1; continue
        worthless = xp is None
        exitp = 0.0 if worthless else xp
        entp = opt["close"]
        out.append(OptionTrade(tr.direction, kind, entp, exitp, exitp - entp,
                               exitp / entp if entp > 1e-9 else 0.0, worthless))
    return out, skipped


def main():
    df = load_daily(str(DATA))
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    levels = detect_levels(df, n=N, k=K)
    base = run_backtest(df, levels, BacktestParams(0.001, 0.003, TM, MH))
    full = run_backtest(df, levels, BacktestParams(0.001, 0.003, TM, MH, require_trend=True))
    print(f"期貨訊號: 不過濾 {len(base)} 筆, 大小流氓過濾 {len(full)} 筆")

    print("抓真實選擇權(不過濾)...")
    ob, sb = real_opts(df, dates, base)
    print("抓真實選擇權(大小流氓過濾)...")
    of, sf = real_opts(df, dates, full)
    pob, pof = summarize_options(ob), summarize_options(of)
    pfb, pff = summarize(base), summarize(full)

    lines = ["# B3: 大小流氓過濾 + 真實 TXO 買方 (EOD)", "",
             f"真實台指期 {len(df)} 根; 近12月真實選擇權配對。HOLD<={HOLD_CAP}天, 權利金~{TARGET_PREMIUM:.0f}。", "",
             "| 版本 | 期貨筆數 | 期貨期望(點) | 買方配對 | 買方勝率 | 買方2x率 | 買方歸零率 | 買方ROI | 買方期望(點) |",
             "|---|---|---|---|---|---|---|---|---|",
             f"| 不過濾(B2) | {len(base)} | {pfb.expectancy:+.1f} | {pob.n_trades} | {pob.win_rate:.2f} "
             f"| {pob.rate_2x:.0%} | {pob.worthless_rate:.0%} | {pob.roi:+.0%} | {pob.expectancy:+.1f} |",
             f"| +大小流氓過濾 | {len(full)} | {pff.expectancy:+.1f} | {pof.n_trades} | {pof.win_rate:.2f} "
             f"| {pof.rate_2x:.0%} | {pof.worthless_rate:.0%} | {pof.roi:+.0%} | {pof.expectancy:+.1f} |",
             "",
             f"> 大小流氓過濾後買方 ROI {pof.roi:+.0%} (配對 {pof.n_trades} 筆)。",
             "> ROI 明顯翻正且樣本夠 -> EOD(一天看一次)可行, 不必盤中盯; 否則需盤中。"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
