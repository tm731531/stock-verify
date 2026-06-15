"""把各 (N,k) 的真實 vs 隨機對照結果彙整成 Markdown 報告。"""


def render_markdown(rows: list) -> str:
    """rows: list of dict, 每個含 n, k, real(Stats), control(Stats)。"""
    lines = [
        "# 軌道鞅大實體K關卡 — 假設檢定結果 (Step A)",
        "",
        "| N | k | 關卡數 | 碰觸 | 真實反應率 | 隨機反應率 | edge(真-隨) | 真實平均幅度 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        real = r["real"]
        ctrl = r["control"]
        edge = real.react_rate - ctrl.react_rate
        lines.append(
            f"| {r['n']} | {r['k']:.1f} | {real.n_levels} | {real.n_touch} "
            f"| {real.react_rate:.2f} | {ctrl.react_rate:.2f} | {edge:.2f} "
            f"| {real.avg_reaction:.1f} |"
        )
    lines += [
        "",
        "> edge > 0 且穩定 → 地基成立(大實體K邊緣確實優於隨機價位)。",
    ]
    return "\n".join(lines)
