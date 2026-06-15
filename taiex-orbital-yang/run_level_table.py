"""產生『軌道策略關卡表』: 餵日線 OHLC -> 排序天梯 CSV + Markdown 預覽。

DEMO 用 ^TWII 加權日線; 實戰請改餵『台指期』日線 OHLC。
未實作 (待確認): 對稱缺口、小妹、X 記號。
"""
import csv
from pathlib import Path

from orbital_yang.data_loader import load_daily
from orbital_yang.level_table import build_table, to_csv_rows

DATA = Path(__file__).parent / "data" / "TWII_daily.csv"
OUT_CSV = Path(__file__).parent / "reports" / "level_table.csv"
OUT_MD = Path(__file__).parent / "reports" / "level_table.md"
WINDOW = 60


def main():
    df = load_daily(str(DATA))
    rows = build_table(df, window=WINDOW)
    csv_rows = to_csv_rows(rows)

    OUT_CSV.parent.mkdir(exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(csv_rows)

    lines = [f"# 軌道策略關卡表 (DEMO: ^TWII, 最後 {WINDOW} 天, 1滿=25點)", "",
             "> 實戰請改餵台指期日線。對稱缺口/小妹/X 待確認未做。", "",
             "| " + " | ".join(csv_rows[0]) + " |",
             "|" + "---|" * len(csv_rows[0])]
    for r in csv_rows[1:]:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cur = [r for r in rows if r.is_current]
    print(f"關卡表: {len(rows)} 排, 當前 {len(cur)} 排 (★)。寫入 {OUT_CSV.name} / {OUT_MD.name}")
    print(f"當前收盤附近 RSI3 註記: " + next((r.note for r in cur if 'RSI3' in r.note), 'n/a'))
    # 印當前價上下各 8 排預覽
    idx = next((i for i, r in enumerate(rows) if r.is_current and r.label.endswith('收')), 0)
    for r in rows[max(0, idx - 8): idx + 9]:
        star = "★" if r.is_current else " "
        print(f"{star} {r.label:14s} {r.price:>9.0f}  {r.man:+6.1f}滿  {r.note}")


if __name__ == "__main__":
    main()
