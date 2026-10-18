"""Test-retest: grade two independent fetches of the same hospitals, measure agreement, write the verified scorecard.
uv run python src/retest.py data/national   (day 1 = DIR/census.csv, day 2 = DIR/day2/census.csv)

Published value per check: 1 if passed on either day and failed on neither... precisely:
  both assessed and equal -> that value; one day only -> that value if it is a pass, blank if it is a fail
  (a fail is published only when it repeats); the two days disagree -> blank ("inconsistent").
Writes DIR/scorecard.csv (verified) and DIR/retest.json; the single-fetch scorecard stays in DIR/scorecard_day1.csv."""
import csv
import json
import shutil
import sys
from pathlib import Path

from scorecard import CHECKS, grade, score


def kappa(pairs):
    """Cohen's kappa for binary pairs; None when undefined (no variation)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    p1, p2 = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    return None if pe == 1 else (po - pe) / (1 - pe)


def combine(a, b):
    if a is not None and b is not None:
        return a if a == b else None
    x = a if a is not None else b
    return x if x == 1 else None


def load(path):
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["index_status"] != "exempt (federal)"]
    for r in rows:
        r.setdefault("city", "")
    return {r["ccn"]: r for r in rows}


def main(d):
    d = Path(d)
    day1, day2 = load(d / "census.csv"), load(d / "day2" / "census.csv")
    out, verified = {}, []
    for name, _ in CHECKS:
        pairs = [(grade(day1[c])[name], grade(day2[c])[name]) for c in day1 if c in day2]
        both = [(a, b) for a, b in pairs if a is not None and b is not None]
        k = kappa(both)
        out[name] = {"both_assessed": len(both), "agree": round(sum(a == b for a, b in both) / len(both), 4) if both else None,
                     "kappa": None if k is None else round(k, 3),
                     "fail_then_pass": sum(a == 0 and b == 1 for a, b in both), "pass_then_fail": sum(a == 1 and b == 0 for a, b in both),
                     "resolved_on_day2": sum(a is None and b is not None for a, b in pairs)}
    for c, r in day1.items():
        g1, g2 = grade(r), grade(day2[c]) if c in day2 else dict.fromkeys(n for n, _ in CHECKS)
        verified.append({n: combine(g1[n], g2[n]) for n, _ in CHECKS})
    # reuse score() for the row layout, then overwrite the checks with the combined values
    rows = score(list(day1.values()))
    for row, g in zip(rows, verified):
        row.update(g)
        req = [g[n] for n, q in CHECKS if q]
        row.update(required_failed=sum(x == 0 for x in req), required_assessed=sum(x is not None for x in req),
                   clean=int(all(x == 1 for x in req)))
    if not (d / "scorecard_day1.csv").exists():
        shutil.copy(d / "scorecard.csv", d / "scorecard_day1.csv")
    with open(d / "scorecard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows({k: "" if v is None else v for k, v in r.items()} for r in rows)
    (d / "retest.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
