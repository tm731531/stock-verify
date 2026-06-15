"""C: 盤整→突破表態 濾網, 在真實台指期上比對『加濾網 vs 不加』的訊號品質。"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest, summarize
from orbital_yang.option_buyer import OptionParams, simulate_option_trades, summarize_options

DATA = Path(__file__).parent / "data" / "TXF_daily.csv"   # 真實台指期
OUT = Path(__file__).parent / "reports" / "step2_congestion.md"
N, K = 20, 1.5
TM, MH = 2.0, 20
CW, CPCT = 10, 0.03        # 盤整定義: 前10根收盤全距/現價 <= 3%
OPT = OptionParams(iv=0.20, expiry_days=5, target_premium=30.0)


def _opt(df, trades):
    return summarize_options(simulate_option_trades(df, trades, OPT))


def main():
    df = load_daily(str(DATA))
    levels = detect_levels(df, n=N, k=K)
    base = run_backtest(df, levels, BacktestParams(0.001, 0.003, TM, MH))
    filt = run_backtest(df, levels, BacktestParams(0.001, 0.003, TM, MH,
                                                   congestion_window=CW, congestion_pct=CPCT))
    pb, pf = summarize(base), summarize(filt)
    ob, of = _opt(df, base), _opt(df, filt)

    lines = ["# C: 盤整→突破表態 濾網 (真實台指期)", "",
             f"資料 {len(df)} 根 ({df['date'].min().date()}~{df['date'].max().date()}), "
             f"N={N} k={K} tm={TM}; 盤整={CW}根全距<={CPCT:.0%}。", "",
             "| 版本 | 期貨交易數 | 期貨勝率 | 期貨期望(點) | 買方2x率 | 買方ROI | 買方期望(點) |",
             "|---|---|---|---|---|---|---|",
             f"| 不加濾網(裸關卡過破) | {pb.n_trades} | {pb.win_rate:.2f} | {pb.expectancy:+.1f} "
             f"| {ob.rate_2x:.0%} | {ob.roi:+.0%} | {ob.expectancy:+.1f} |",
             f"| 加濾網(等表態) | {pf.n_trades} | {pf.win_rate:.2f} | {pf.expectancy:+.1f} "
             f"| {of.rate_2x:.0%} | {of.roi:+.0%} | {of.expectancy:+.1f} |",
             "",
             "> 濾網若讓交易數下降但勝率/2x率/期望上升 -> 『等表態』有效濾掉雜訊。"]
    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(md)
    print(f"不加: 期貨{pb.n_trades}筆 勝{pb.win_rate:.2f} 期望{pb.expectancy:+.1f}點 | 買方2x{ob.rate_2x:.0%} ROI{ob.roi:+.0%}")
    print(f"加濾: 期貨{pf.n_trades}筆 勝{pf.win_rate:.2f} 期望{pf.expectancy:+.1f}點 | 買方2x{of.rate_2x:.0%} ROI{of.roi:+.0%}")


if __name__ == "__main__":
    main()
