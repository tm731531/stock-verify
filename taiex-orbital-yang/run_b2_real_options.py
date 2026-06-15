"""B2: 用真實 TXO 權利金重跑買方回測 (取代 BS 模型)。

每訊號: 進場當天鏈挑 ~30 點真實選擇權(多買call/空買put), 持有上限 3 天,
查出場當天該口真實收盤算損益。查不到(到期/未交易)視為歸零。
為控資料量只跑近 12 個月訊號; 每日鏈快取本地。
"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest
from orbital_yang.option_buyer import OptionTrade, summarize_options
from orbital_yang.txo_data import fetch_chain, pick_entry_option, lookup_premium

DATA = Path(__file__).parent / "data" / "TXF_daily.csv"
OUT = Path(__file__).parent / "reports" / "b2_real_options.md"
N, K = 20, 1.5
SIG = BacktestParams(breakout_pct=0.001, stop_buffer_pct=0.003, target_mult=2.0, max_hold=20)
TARGET_PREMIUM = 30.0
HOLD_CAP = 3                 # 選擇權最多抱 3 個交易日
DATE_FLOOR = "2025-06-01"    # 只跑近 12 個月訊號 (控資料量)


def main():
    df = load_daily(str(DATA))
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    levels = detect_levels(df, n=N, k=K)
    trades = run_backtest(df, levels, SIG)
    trades = [t for t in trades if dates[t.entry_idx] >= DATE_FLOOR]
    print(f"近12月訊號 {len(trades)} 筆, 逐筆抓真實選擇權鏈 ...")

    otrades, skipped = [], 0
    for tr in trades:
        kind = "call" if tr.direction == "long" else "put"
        ed = dates[tr.entry_idx]
        xi = min(tr.exit_idx, tr.entry_idx + HOLD_CAP)
        xd = dates[xi]
        try:
            ce = fetch_chain(ed)
            opt = pick_entry_option(ce, kind, TARGET_PREMIUM)
            if opt is None:
                skipped += 1; continue
            cx = fetch_chain(xd)
            xp = lookup_premium(cx, opt["contract_date"], opt["strike_price"], kind)
        except Exception as e:
            print(f"  {ed} 抓取失敗: {e}"); skipped += 1; continue
        worthless = xp is None
        exit_prem = 0.0 if worthless else xp
        entry_prem = opt["close"]
        pnl = exit_prem - entry_prem
        mult = exit_prem / entry_prem if entry_prem > 1e-9 else 0.0
        otrades.append(OptionTrade(tr.direction, kind, entry_prem, exit_prem, pnl, mult, worthless))
        print(f"  {ed}->{xd} {kind} 履約{opt['strike_price']:.0f} "
              f"進{entry_prem:.1f}->出{exit_prem:.1f} ({mult:.1f}x)")

    p = summarize_options(otrades)
    lines = ["# B2 真實 TXO 權利金買方回測", "",
             f"近12月訊號 {len(trades)} 筆, 成功配對 {len(otrades)} 筆 (跳過 {skipped}), "
             f"持有<= {HOLD_CAP} 天, 目標權利金 {TARGET_PREMIUM:.0f} 點。", "",
             "| 指標 | 真實值 |", "|---|---|",
             f"| 配對交易數 | {p.n_trades} |",
             f"| 勝率 | {p.win_rate:.2f} |",
             f"| 2x 率 | {p.rate_2x:.0%} |",
             f"| 3x 率 | {p.rate_3x:.0%} |",
             f"| 歸零率 | {p.worthless_rate:.0%} |",
             f"| 期望(點) | {p.expectancy:+.1f} |",
             f"| ROI | {p.roi:+.0%} |",
             f"| 每筆 NT$ | {p.expectancy*50:+,.0f} |",
             f"| 平均賺 / 賠 | {p.avg_win:+.1f} / {p.avg_loss:+.1f} |",
             "", "> 真實成交價, 非模型。對照 BS 模型版 (step2b): IV20%/5日約 ROI+117%、2x21%、歸零25%。"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
