"""Count/dispersion + units check on populated cells, from census.py's cached results (or re-parsed raw prefixes; no new downloads).
Run after census.py: uv run python src/dispersion.py [--out data/national --raw data/raw/national]"""
import argparse
import csv
import json
import pickle
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import census  # noqa: E402
import hpt  # noqa: E402

BINS = ["1 through 10", "11-30", "31-150", ">150", "missing/0/other"]


def load(url):
    path = census.raw_path(hpt.unwrap_urldefense(url)[0])
    done = census.RAW / "done" / (path.stem + ".pkl")
    if done.exists():
        return pickle.loads(done.read_bytes()).get("stats")
    return census.parse_file(path)[1] if path.exists() and path.stat().st_size else None


def summarize(cells):
    bins = Counter(hpt.n_bin(c[0]) for c in cells)
    s = [(hpt.n_bin(c[0]), hpt.dispersion(c[1], c[2])) for c in cells]
    band = Counter()  # negotiated $ outside [P10, P90], by count bin
    for c, a, b, d, *_ in cells:
        if None not in (a, b, d):
            band[hpt.n_bin(c), "n"] += 1
            band[hpt.n_bin(c), "out"] += d < a or d > b
    sv = sorted(x for _, x in s if x is not None)
    safe = sum(1 for b, x in s if b == ">150" and x is not None and x < 0.3)
    q = lambda p: round(sv[min(len(sv) - 1, int(p * len(sv)))], 3) if sv else ""
    return {"cells": len(cells), **{f"n_{k}": bins[k] for k in BINS}, "s_n": len(sv),
            "s_p10": q(.1), "s_p25": q(.25), "s_p50": q(.5), "s_p75": q(.75), "s_p90": q(.9),
            "s_gt_0.3": round(sum(x > 0.3 for x in sv) / len(sv), 4) if sv else "",
            "n150_and_s_lt_0.3": safe, "n_gt150_safe_share": round(safe / bins[">150"], 4) if bins[">150"] else "",
            **{f"band_out_{k}": f"{band[k, 'out']}/{band[k, 'n']}" for k in BINS[:4]}, "safe_share_of_s_cells": round(safe / len(sv), 4) if sv else ""}


def code_family(t):
    t = t.upper().replace("_", "-")
    return "DRG" if "DRG" in t else t if t in ("CPT", "HCPCS", "RC", "NDC", "CDM", "LOCAL") else "other/blank"


def units(cells):
    """Negotiated $ vs allowed median, by code family / setting / billing class / methodology; ratio = median / negotiated $.
    A degenerate band (P10 == P90) puts any off-by-a-cent rate "outside", so the band test is also run on non-degenerate
    cells with a 5% tolerance."""
    g = defaultdict(lambda: [0, 0, [], 0, 0, 0, 0, 0])  # n, out, ratios, near-int, degenerate, median==negotiated, nondeg n, nondeg out(5%)
    for c, a, b, d, med, _, ct, setting, bc, meth, *_ in cells:
        if None in (a, b, d) or not d or not med:
            continue
        r, deg = med / d, a == b
        for key in (("code", code_family(ct)), ("setting", setting.lower()), ("billing_class", bc.lower()), ("methodology", meth.lower()),
                    ("matched", unit_match(ct, meth)), ("all", "")):
            x = g[key]
            x[0] += 1
            x[1] += d < a or d > b
            x[2].append(r)
            x[3] += round(r) >= 2 and abs(r - round(r)) < 0.02
            x[4] += deg
            x[5] += med == d
            if not deg:
                x[6] += 1
                x[7] += d < 0.95 * a or d > 1.05 * b
    return {f"{k}={v}": {"n": n, "band_out": round(o / n, 4), "ratio_p25_p50_p75": [round(x, 3) for x in statistics.quantiles(rs, n=4)] if n > 1 else rs,
                         "ratio_within_10pct_of_1": round(sum(0.9 <= x <= 1.1 for x in rs) / n, 4), "ratio_near_integer_ge2": round(i / n, 4),
                         "degenerate_band": round(dg / n, 4), "median_equals_negotiated": round(eq / n, 4),
                         "nondegenerate_n": nn, "nondegenerate_band_out_5pct": round(no / nn, 4) if nn else ""}
            for (k, v), (n, o, rs, i, dg, eq, nn, no) in sorted(g.items()) if n >= 30}


def unit_match(code_type, meth):
    """Cells where a negotiated rate and a claim-level allowed amount plausibly share units: DRG / case-rate (per stay)
    and CPT/HCPCS fee-schedule rates (per service)."""
    fam, m = code_family(code_type), meth.lower()
    if fam == "DRG" or "case rate" in m:
        return "per-case (DRG/case rate)"
    if fam in ("CPT", "HCPCS") and "fee schedule" in m:
        return "per-service (CPT/HCPCS fee schedule)"
    return "unmatched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=census.OUT)
    ap.add_argument("--raw", type=Path, default=census.RAW)
    a = ap.parse_args()
    census.RAW, OUT = a.raw, a.out
    rows = [r for r in csv.DictReader(open(OUT / "census.csv", encoding="utf-8")) if r["mrf_url"] and r["sample_n"]]
    out, pooled, seen = [], [], set()
    for r in rows:
        if r["mrf_url"] in seen:
            continue
        seen.add(r["mrf_url"])
        st = load(r["mrf_url"])
        if not st or not st.cells:
            continue
        pooled += [(*c, r["ccn"]) for c in st.cells]
        out.append({"ccn": r["ccn"], "name": r["name"], **summarize(st.cells)})
        print(out[-1]["ccn"], out[-1]["cells"], out[-1]["safe_share_of_s_cells"], flush=True)
    with open(OUT / "dispersion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    per = [o["safe_share_of_s_cells"] for o in out if o["safe_share_of_s_cells"] != ""]
    res = {"pooled": summarize(pooled), "pooled_pct_alg_rows": summarize([c for c in pooled if c[5]]), "mrfs": len(out),
           "per_mrf_safe_share_median": statistics.median(per) if per else None,
           "mrfs_majority_safe": sum(p > 0.5 for p in per), "units": units(pooled)}
    (OUT / "dispersion_summary.json").write_text(json.dumps(res, indent=1))
    keys = ["count", "p10", "p90", "negotiated_dollar", "median", "pct_or_alg_row", *hpt.UNIT_KEYS, "ccn"]
    pick = random.Random(20261018).sample([c for c in pooled if c[3]], min(50, sum(1 for c in pooled if c[3])))
    (OUT / "units_sample.json").write_text(json.dumps([{**dict(zip(keys, c)), "median_over_negotiated": round(c[4] / c[3], 3)} for c in pick], indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
