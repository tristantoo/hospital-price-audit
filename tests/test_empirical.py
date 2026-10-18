import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "paper"), str(ROOT / "src")]
from empirical import cell, delta  # noqa: E402


def test_rounding_gap():
    assert [delta(n, 90) for n in (10, 11, 12, 20)] == [0.9, 0.0, 0.1, 0.9]
    assert (delta(30, 50), delta(31, 50)) == (0.5, 0.0)


def test_cell_masking_sandwich_and_subcent():
    row = lambda n, p10, med, p90: (n, p10, p90, None, med, True, "MS-DRG")
    assert cell(row("1 through 10", 100.0, 100.0, 100.0))["masked"]
    assert cell(row("0", 1.0, 1.0, 1.0)) is None
    x = cell(row("30", 100.0, 150.0, 200.0))
    assert x["b90"] > 0 and not x["tie"] and not x["subcent"]
    assert cell(row("30", 100.0, 200.0, 200.0))["b90"] == 0.0  # med == P90 forces a zero spacing at the P90 rank
    assert cell(row("30", 100.0, 150.005, 200.0))["subcent"]
