"""Step A 主流程(修正對照組): 載日線 -> 掃(N,k)×多空 -> 真實 vs 均勻/方向匹配對照 -> 報告。"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.hypothesis_test import (
    TestParams, evaluate_levels, control_uniform, control_matched,
)
from orbital_yang.report import render_markdown

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step_a_result.md"

N_GRID = [10, 20, 40]
K_GRID = [1.5, 2.0, 2.5, 3.0]
PARAMS = TestParams(epsilon_pct=0.001, window=10, reaction_pct=0.005)  # 0.1% / 0.5%
CONTROL_SETS = 50
SEED = 42


def main():
    df = load_daily(str(DATA))
    print(f"資料: {len(df)} 根, {df['date'].min().date()} ~ {df['date'].max().date()}")

    rows = []
    for n in N_GRID:
        for k in K_GRID:
            levels = detect_levels(df, n=n, k=k)
            for kind in ("support", "resistance"):
                subset = [lv for lv in levels if lv.kind == kind]
                real = evaluate_levels(df, subset, PARAMS)
                uni = control_uniform(df, subset, PARAMS, CONTROL_SETS, SEED)
                mat = control_matched(df, subset, PARAMS, CONTROL_SETS, SEED)
                rows.append({"n": n, "k": k, "kind": kind,
                             "real": real, "uniform": uni, "matched": mat})
                edge = real.react_rate - mat.react_rate
                print(f"N={n} k={k} {kind:10s}: 關卡{real.n_levels:3d} 碰{real.n_touch:3d} "
                      f"真{real.react_rate:.2f} 勻{uni.react_rate:.2f} "
                      f"配{mat.react_rate:.2f} edge{edge:+.2f}")

    md = render_markdown(rows)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
