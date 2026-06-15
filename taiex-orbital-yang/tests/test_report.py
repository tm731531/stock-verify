from orbital_yang.hypothesis_test import Stats
from orbital_yang.report import render_markdown


def test_render_markdown_per_kind_and_edge():
    rows = [
        {"n": 20, "k": 2.0, "kind": "support",
         "real": Stats(5, 4, 3, 0.75, 8.0),
         "uniform": Stats(50, 40, 12, 0.30, 6.0),
         "matched": Stats(50, 38, 15, 0.40, 6.0)},
    ]
    md = render_markdown(rows)
    assert "| N | k | 多空 |" in md
    assert "支撐" in md
    assert "0.75" in md and "0.30" in md and "0.40" in md
    # edge = real - matched = 0.75 - 0.40 = 0.35
    assert "+0.35" in md
