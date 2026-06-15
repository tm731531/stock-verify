from orbital_yang.hypothesis_test import Stats
from orbital_yang.report import render_markdown


def test_render_markdown_contains_grid_and_edge():
    rows = [
        {"n": 20, "k": 2.0, "real": Stats(5, 4, 3, 0.75, 8.0),
         "control": Stats(50, 40, 12, 0.30, 6.0)},
    ]
    md = render_markdown(rows)
    assert "| N | k |" in md
    assert "20" in md and "2.0" in md
    assert "0.75" in md and "0.30" in md
    # edge = 真實 react 率 - 對照 react 率
    assert "0.45" in md
