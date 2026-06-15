"""Step A 主流程: 載日線 -> 掃 (N,k) -> 真實 vs 隨機對照 -> 出報告。"""
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.body_levels import detect_levels
from orbital_yang.hypothesis_test import TestParams, evaluate_levels, random_control
from orbital_yang.report import render_markdown

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT = Path(__file__).parent / "reports" / "step_a_result.md"

N_GRID = [10, 20, 40]
K_GRID = [1.5, 2.0, 2.5, 3.0]
PARAMS = TestParams(epsilon=30.0, window=10, reaction=100.0)  # 點數;指數級距
CONTROL_SETS = 50
SEED = 42


def main():
    df = load_daily(str(DATA))
    print(f"資料: {len(df)} 根, {df['date'].min().date()} ~ {df['date'].max().date()}")

    rows = []
    for n in N_GRID:
        for k in K_GRID:
            levels = detect_levels(df, n=n, k=k)
            real = evaluate_levels(df, levels, PARAMS)
            ctrl = random_control(df, levels, PARAMS, n_sets=CONTROL_SETS, seed=SEED)
            rows.append({"n": n, "k": k, "real": real, "control": ctrl})
            print(f"N={n} k={k}: 關卡{real.n_levels} 碰{real.n_touch} "
                  f"真{real.react_rate:.2f} 隨{ctrl.react_rate:.2f}")

    md = render_markdown(rows)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(md)
    print(f"\n報告寫入 {OUT}")
    print(md)


if __name__ == "__main__":
    main()
