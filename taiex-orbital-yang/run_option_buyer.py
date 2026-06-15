"""Step 2B: 把 tm=2.0 訊號當『選擇權買方』, 掃 IV × 到期天數, 報告倍數命中率/期望/歸零。

買方語言: 軌道鞅瞄準 2-3 倍 (兩三滿距離)。注意: 我們用日線訊號(慢), 他實際盤中進場,
故 2x 命中率可能被低估, 此版偏保守。
"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.backtest import BacktestParams, run_backtest
from orbital_yang.option_buyer import OptionParams, simulate_option_trades, summarize_options

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step2b_option_buyer.md"

N, K = 20, 1.5
SIG = BacktestParams(breakout_pct=0.001, stop_buffer_pct=0.003, target_mult=2.0, max_hold=20)
IV_GRID = [0.15, 0.20, 0.25]
EXPIRY_GRID = [3, 5]
TARGET_PREMIUM = 30.0
PV = 50.0


def main():
    df = load_daily(str(DATA))
    levels = detect_levels(df, n=N, k=K)
    trades = run_backtest(df, levels, SIG)
    print(f"資料 {len(df)} 根, 訊號交易 {len(trades)} 筆 (tm=2.0)")

    header = ("| IV | 到期日 | 筆數 | 勝率 | 平均賺 | 平均賠 | 賠率 | 期望(點) | ROI | "
              "2x率 | 3x率 | 歸零率 | 每筆NT$ | 最大回撤(點) |")
    sep = "|" + "---|" * 14
    lines = ["# Step 2B 選擇權買方 (簡化 BS, 權利金~30, tm=2.0 訊號)", "",
             f"資料 {len(df)} 根, {len(trades)} 筆訊號, TXO {PV:.0f}元/點。",
             "> 模型數字, 吃 IV/到期假設; 日線訊號偏慢 -> 2x 率保守。", "",
             header, sep]
    for iv in IV_GRID:
        for ed in EXPIRY_GRID:
            params = OptionParams(iv=iv, expiry_days=ed, target_premium=TARGET_PREMIUM, point_value=PV)
            p = summarize_options(simulate_option_trades(df, trades, params))
            lines.append(
                f"| {iv:.0%} | {ed} | {p.n_trades} | {p.win_rate:.2f} | {p.avg_win:+.1f} "
                f"| {p.avg_loss:+.1f} | {p.payoff:.2f} | {p.expectancy:+.1f} | {p.roi:+.0%} "
                f"| {p.rate_2x:.0%} | {p.rate_3x:.0%} | {p.worthless_rate:.0%} "
                f"| {p.expectancy*PV:+,.0f} | {p.max_drawdown:+.0f} |"
            )
            print(f"IV={iv:.0%} 到期{ed}日: 筆{p.n_trades} 勝{p.win_rate:.2f} "
                  f"期望{p.expectancy:+.1f}點 ROI{p.roi:+.0%} 2x{p.rate_2x:.0%} 歸零{p.worthless_rate:.0%}")

    md = "\n".join(lines) + "\n"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
