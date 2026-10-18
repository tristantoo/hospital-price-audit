"""Per-hospital compliance scorecard from a census.csv, plus share passing each check.
uv run python src/scorecard.py data/national   (stratified estimates, needs sample.csv)
uv run python src/scorecard.py data/recon      (Virginia: a census, plain k/N)
Each check is 1 (pass), 0 (fail) or blank (not assessable: upstream step failed, or the failure may be ours)."""
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from census import lu_date  # noqa: E402
from national import strat_prop  # noqa: E402

AS_OF = date(2026, 10, 17)  # fetch date of the census
FIELDS = {"median_amount", "10th_percentile", "90th_percentile", "count"}
# Index failures that are the hospital's: blocked even to a browser UA, broken TLS, server error, 200 that is not a valid file.
# 404/400/timeouts are left blank: our domain may be wrong or the failure transient.
HOSPITAL_FAULT = ("403", "SSLError", "500", "200")
# (name, required by 45 CFR 180 / CMS spec?). Advisory: bot_barrier (the rule bans accounts/PII gates, not UA filtering per se);
# open_format (CMS FAQ reportedly allows .zip/.gz, unverified against the FAQ text);
# fields_populated (count 0 with blank percentiles is permitted when there is no remittance data in the lookback,
# so an unpopulated file is not provably noncompliant -- reported as data availability).
CHECKS = [("index_valid", 1), ("location_listed", 1), ("file_retrievable", 1), ("open_format", 0), ("no_bot_barrier", 0),
          ("template_v3", 1), ("updated_12mo", 1), ("attested", 1), ("fields_present", 1), ("fields_populated", 0),
          ("no_count0_amounts", 1)]


def grade(r):
    """census row -> {check: 1/0/None}."""
    st, d = r["index_status"], r["defects"]
    g = dict.fromkeys(name for name, _ in CHECKS)
    if st.startswith("ok"):
        g["index_valid"] = 1
    elif st.startswith("fail ["):
        codes = [a.split(": ")[-1].split(" ")[0] for a in st[6:-1].split("; ")]
        g["index_valid"] = 0 if all(c in HOSPITAL_FAULT for c in codes) else None
    if g["index_valid"]:
        # empty index = hospital's fault; no fuzzy match among entries may be our matcher's
        g["location_listed"] = 1 if r["mrf_url"] else 0 if st == "ok but no location entries" else None
    if g["location_listed"]:
        g["no_bot_barrier"] = int("to plain client" not in d)  # recon tags "403 to ...", national "403/406 to ..."
        g["file_retrievable"] = {"200": 1, "403": 0, "404": 0}.get(r["http"])
        if r["format"].startswith("html"):
            g["file_retrievable"] = 0
    if g["file_retrievable"]:
        g["open_format"] = int(".zip" not in d)
    if r["sample_n"]:
        v = r["version"].strip()
        g["template_v3"] = int(v.lstrip("vV").split(".")[0] == "3")
        lu = lu_date(r["last_updated_on"])
        g["updated_12mo"] = int(lu is not None and (AS_OF - lu).days <= 365)
        g["attested"] = int(r["attestation"].strip().lower() == "true")
        g["fields_present"] = int(set(r["fields_present"].split("|")) >= FIELDS)
        g["no_count0_amounts"] = int("count=0" not in d)
        # required where the rate is a percentage/algorithm; files with no such rows fall back to all payer rows
        share = r["req_median_share"] if r["req_rows"] not in ("", "0") else r["median_share"]
        g["fields_populated"] = int(float(share or 0) > 0.1) if g["fields_present"] else 0
    return g


def score(rows):
    out = []
    for r in rows:
        g = grade(r)
        req = [g[n] for n, q in CHECKS if q]
        out.append({"ccn": r["ccn"], "name": r["name"], "city": r["city"], "domain": r["domain"], **g,
                    "required_failed": sum(x == 0 for x in req), "required_assessed": sum(x is not None for x in req),
                    # clean = every required check assessed and passed
                    "clean": int(all(x == 1 for x in req))})
    return out


def main(d):
    d = Path(d)
    cen = [r for r in csv.DictReader(open(d / "census.csv", encoding="utf-8")) if r["index_status"] != "exempt (federal)"]
    for r in cen:
        r.setdefault("city", "")
    sc = score(cen)
    with open(d / "scorecard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(sc[0]))
        w.writeheader()
        w.writerows({k: "" if v is None else v for k, v in r.items()} for r in sc)
    smp = d / "sample.csv"
    strata = {r["ccn"]: (r["stratum"], int(r["N_h"])) for r in csv.DictReader(open(smp, encoding="utf-8"))} if smp.exists() else {}
    summ = {"as_of": str(AS_OF), "hospitals": len(sc), "design": "stratified sample" if strata else "census (no sampling error)"}
    for name in [n for n, _ in CHECKS] + ["clean"]:
        got = [r for r in sc if r[name] is not None]
        k = sum(r[name] for r in got)
        row = {"pass": k, "assessed": len(got), "not_assessable": len(sc) - len(got)}
        if strata and got:
            sizes = {s: n for s, n in strata.values() if any(strata[r["ccn"]][0] == s for r in got)}
            p, se, ci = strat_prop([r[name] for r in got], [strata[r["ccn"]][0] for r in got], sizes)
            row.update(p=round(p, 4), ci95=[round(ci[0], 4), round(ci[1], 4)])
        elif got:
            row["p"] = round(k / len(got), 4)
        summ[name] = row
    by = defaultdict(list)
    for r in sc:
        by[r["domain"] or "(no domain)"].append(r)
    summ["worst domains (hospitals, required fails)"] = sorted(
        ([dom, len(rs), sum(r["required_failed"] for r in rs)] for dom, rs in by.items()), key=lambda x: -x[2])[:15]
    (d / "scorecard_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
