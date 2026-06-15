"""抓真實台指期日線 -> data/TXF_daily.csv, 並用它重生關卡表。"""
from pathlib import Path

from orbital_yang.futures_data import fetch_txf_daily, save_csv
from orbital_yang.level_table import build_table, to_csv_rows
import csv

START = "2024-01-01"
END = "2026-06-15"
HERE = Path(__file__).parent
CSV = HERE / "data" / "TXF_daily.csv"
LVL_CSV = HERE / "reports" / "level_table_txf.csv"


def main():
    print(f"抓 FinMind 台指期 {START} ~ {END} ...")
    df = fetch_txf_daily(START, END)
    save_csv(df, str(CSV))
    print(f"台指期日線: {len(df)} 根, {df['date'].min().date()} ~ {df['date'].max().date()} -> {CSV.name}")
    print(df.tail(3).to_string(index=False))

    rows = build_table(df, window=60)
    LVL_CSV.parent.mkdir(exist_ok=True)
    with open(LVL_CSV, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(to_csv_rows(rows))
    print(f"\n關卡表(台指期)寫入 {LVL_CSV.name}; 當前價附近預覽:")
    idx = next((i for i, r in enumerate(rows) if r.is_current and r.label.endswith('收')), 0)
    for r in rows[max(0, idx - 6): idx + 7]:
        star = "★" if r.is_current else " "
        print(f"{star} {r.label:14s} {r.price:>9.0f}  {r.man:+6.1f}滿  {r.note}")


if __name__ == "__main__":
    main()
