"""Section 5 numbers: how much of the rule's bias real price files are exposed to.
uv run python paper/empirical.py   (reads census.py's cached per-file results; no downloads)

Per populated cell: count n, published P10/P90. Exact n is known only for n >= 11 (1-10 is masked).
Plug-in rule-attributable relative bias (first-order, lognormal):  delta_n * s / ((n+1) * phi(z_p)),
with s = log(P90/P10)/2.563 from the published values. Files are the unit: each file gets equal weight,
and intervals are percentile bootstraps over files (B = 2000)."""
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import census  # noqa: E402
import dispersion  # noqa: E402
import hpt  # noqa: E402

PHI = {50: 1 / math.sqrt(2 * math.pi), 90: math.exp(-1.2815516 ** 2 / 2) / math.sqrt(2 * math.pi)}


def delta(n, P):
    """Rounding gap ceil(h) - h of the type-7 position h = (n-1)p + 1."""
    return ((-(n - 1) * P) % 100) / 100


def cell(c):
    """(count, p10, p90, ...) -> dict or None. n=None for masked cells."""
    raw, p10, p90 = c[0], c[1], c[2]
    n = hpt.num(raw)
    if raw != "1 through 10" and (n is None or n < 1):
        return None
    n = None if raw == "1 through 10" else int(n)
    s = hpt.dispersion(p10, p90)
    med = c[4]
    vals = [v for v in (p10, med, p90) if v is not None]
    out = {"masked": n is None or n <= 10, "s": s, "degenerate": p10 is not None and p10 == p90,
           # kill checks: ties make the continuous-bias theory moot; sub-cent values cannot be observed payments
           "tie": None in (p10, med, p90) or p10 == med or med == p90,
           "subcent": any(abs(v * 100 - round(v * 100)) > 1e-6 for v in vals),
           # per-unit division (CMS FAQ p.13) can legitimately give sub-cent values; per-case DRG amounts cannot
           "drg": "DRG" in str(c[6]).upper()}
    if n and n >= 11 and s is not None:
        # sandwich: med == P90 forces X_(k50..k90) equal, so the spacing at the P90 rank is 0 (likewise P10 == med at the median)
        out["b90"] = 0.0 if med == p90 else delta(n, 90) * s / ((n + 1) * PHI[90])
        out["b50"] = 0.0 if p10 == med else delta(n, 50) * s / ((n + 1) * PHI[50])
    return out


def file_stats(cells):
    cs = [x for x in map(cell, cells) if x]
    known = [x for x in cs if "b90" in x]
    if not cs:
        return None
    share = lambda xs, f: sum(map(f, xs)) / len(xs) if xs else None
    return {"cells": len(cs), "masked": share(cs, lambda x: x["masked"]),
            "masked_degenerate": share([x for x in cs if x["masked"]], lambda x: x["degenerate"]),
            "known": len(known), "b90_gt1": share(known, lambda x: x["b90"] > 0.01), "b90_gt5": share(known, lambda x: x["b90"] > 0.05),
            "b50_gt1": share(known, lambda x: x["b50"] > 0.01),
            "tie": share(cs, lambda x: x["tie"]), "tie_known_n": share(known, lambda x: x["tie"]),
            "subcent": share(cs, lambda x: x["subcent"]), "subcent_known_n": share(known, lambda x: x["subcent"]),
            "subcent_drg": share([x for x in cs if x["drg"]], lambda x: x["subcent"]),
            "b90_median": statistics.median(x["b90"] for x in known) if known else None,
            # exposed at P90: masked with a non-degenerate band (published P90 = sample max of distinct values),
            # or known n with plug-in rule bias > 1%. Degenerate masked cells (P10 == P90: n = 1 or tied values) are unaffected.
            "exposed90": share(cs, lambda x: (x["masked"] and not x["degenerate"]) or x.get("b90", 0) > 0.01)}


def boot(vals, B=2000, seed=20261018):
    vals = [v for v in vals if v is not None]
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(vals, k=len(vals))) for _ in range(B))
    return {"files": len(vals), "mean": round(statistics.fmean(vals), 4), "ci95": [round(means[int(.025 * B)], 4), round(means[int(.975 * B)], 4)]}


def main():
    census.RAW = ROOT / "data/raw/national"
    rows = [r for r in csv.DictReader(open(ROOT / "data/national/census.csv", encoding="utf-8")) if r["mrf_url"] and r["sample_n"]]
    per, pooled, seen = [], [], set()
    for r in rows:
        if r["mrf_url"] in seen:
            continue
        seen.add(r["mrf_url"])
        st = dispersion.load(r["mrf_url"])
        if st and st.cells:
            fs = file_stats(st.cells)
            if fs:
                per.append({"ccn": r["ccn"], **fs})
                pooled += [x for x in map(cell, st.cells) if x]
    known = [x for x in pooled if "b90" in x]
    q = lambda xs, p: round(sorted(xs)[int(p * (len(xs) - 1))], 4)
    out = {"files": len(per), "cells": len(pooled), "known_n_cells": len(known),
           "per_file (equal weight, bootstrap over files)": {k: boot([f[k] for f in per]) for k in
                                                             ("masked", "masked_degenerate", "b90_gt1", "b90_gt5", "b50_gt1", "b90_median", "exposed90", "tie", "tie_known_n", "subcent", "subcent_known_n", "subcent_drg")},
           "pooled known-n cells": {"b90_p25_p50_p75_p90": [q([x["b90"] for x in known], p) for p in (.25, .5, .75, .9)],
                                    "b90_gt1": round(sum(x["b90"] > .01 for x in known) / len(known), 4),
                                    "b90_gt5": round(sum(x["b90"] > .05 for x in known) / len(known), 4)}}
    (ROOT / "paper/empirical.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
