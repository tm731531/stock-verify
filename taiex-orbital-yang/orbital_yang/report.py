"""彙整 (N,k) × 多空 的真實 vs (均勻/方向匹配)對照, 輸出 Markdown。"""


def render_markdown(rows: list) -> str:
    """rows: list of dict {n, k, kind, real, uniform, matched} (後三者為 Stats)。"""
    lines = [
        "# 軌道鞅大實體K關卡 — 假設檢定結果 (Step A, 修正對照組)",
        "",
        "門檻為百分比; 對照組『方向匹配』= 同根收盤同側固定偏移帶。edge = 真實 - 方向匹配。",
        "",
        "| N | k | 多空 | 關卡數 | 碰觸 | 真實反應率 | 均勻對照 | 方向匹配對照 | edge(真-匹配) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        real, uni, mat = r["real"], r["uniform"], r["matched"]
        edge = real.react_rate - mat.react_rate
        kind_zh = "支撐" if r["kind"] == "support" else "壓力"
        lines.append(
            f"| {r['n']} | {r['k']:.1f} | {kind_zh} | {real.n_levels} | {real.n_touch} "
            f"| {real.react_rate:.2f} | {uni.react_rate:.2f} | {mat.react_rate:.2f} "
            f"| {edge:+.2f} |"
        )
    lines += [
        "",
        "> 看『方向匹配對照』欄: edge 穩定 > 0 才代表大實體K選擇真的加值(贏過同側隨機線)。",
        "> 『均勻對照』欄留作對比, 凸顯舊方法在多頭市場對支撐的偏誤。",
    ]
    return "\n".join(lines)
