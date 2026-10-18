"""National census helpers: stratified sample, domain resolution, design-based summary.
uv run python src/national.py sample|domains|summary"""
import csv
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
NAT, RAW = ROOT / "data/national", ROOT / "data/raw"
SEED, N = 20261018, 300
TYPES = {"Acute Care Hospitals": "acute", "Critical Access Hospitals": "cah"}
REGION = {r: s.split() for r, s in {
    "Northeast": "CT ME MA NH RI VT NJ NY PA",
    "Midwest": "IL IN MI OH WI IA KS MN MO NE ND SD",
    "South": "DE DC FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX",
    "West": "AZ CO ID MT NV NM UT WY AK CA HI OR WA"}.items()}
STATE_REGION = {s: r for r, ss in REGION.items() for s in ss}


def allocate(sizes, n):
    """Proportional allocation, largest remainder. sizes: {stratum: N_h} -> {stratum: n_h}, sum n."""
    tot = sum(sizes.values())
    q = {k: n * v / tot for k, v in sizes.items()}
    a = {k: int(x) for k, x in q.items()}
    for k in sorted(q, key=lambda k: (a[k] - q[k], k))[: n - sum(a.values())]:
        a[k] += 1
    return a


def sample():
    hgi = csv.DictReader(open(RAW / "Hospital_General_Information.csv", encoding="utf-8-sig"))
    # Federally owned hospitals (VA, DoD, IHS = "Government - Federal") are exempt from 45 CFR 180; territories have no Census region.
    frame = [{"ccn": h["Facility ID"], "name": h["Facility Name"], "city": h["City/Town"], "state": h["State"],
              "stratum": f"{STATE_REGION[h['State']]}|{TYPES[h['Hospital Type']]}"}
             for h in hgi if h["Hospital Type"] in TYPES and h["State"] in STATE_REGION and h["Hospital Ownership"] != "Government - Federal"]
    sizes = Counter(r["stratum"] for r in frame)
    alloc, rng, picked = allocate(sizes, N), random.Random(SEED), set()
    for s in sorted(sizes):
        picked |= set(rng.sample(sorted(r["ccn"] for r in frame if r["stratum"] == s), alloc[s]))
    NAT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("frame.csv", frame), ("sample.csv", [r for r in frame if r["ccn"] in picked])):
        with open(NAT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, [*frame[0], "N_h", "n_h", "sampled"])
            w.writeheader()
            w.writerows({**r, "N_h": sizes[r["stratum"]], "n_h": alloc[r["stratum"]], "sampled": int(r["ccn"] in picked)} for r in rows)
    print(len(frame), dict(sorted(alloc.items())))


def host(url):
    h = urlsplit(url if "//" in url else "//" + url).hostname or ""
    return h[4:] if h.startswith("www.") else h


def domains():
    """DoltHub hospital-price-transparency-v3 `hospitals` -> domain per sampled CCN. Keeps hand-filled rows already in domains.csv."""
    cache = RAW / "dolthub_hospitals.json"
    if not cache.exists():
        api = "https://www.dolthub.com/api/v1alpha1/dolthub/hospital-price-transparency-v3/main"
        rows, off = [], 0
        while True:
            q = f"SELECT cms_certification_num, name, homepage_url, chargemaster_url FROM hospitals ORDER BY cms_certification_num LIMIT 1000 OFFSET {off}"
            got = requests.get(api, params={"q": q}, timeout=120).json()["rows"]
            rows += got
            off += 1000
            if len(got) < 1000:
                break
        cache.write_text(json.dumps(rows))
    dolt = {r["cms_certification_num"]: r for r in json.loads(cache.read_text())}
    hifld = hifld_rows()
    hgi = {h["Facility ID"]: h for h in csv.DictReader(open(RAW / "Hospital_General_Information.csv", encoding="utf-8-sig"))}
    out = NAT / "domains.csv"
    old = {r["ccn"]: r for r in csv.DictReader(open(out, encoding="utf-8"))} if out.exists() else {}
    rows = []
    for s in csv.DictReader(open(NAT / "sample.csv", encoding="utf-8")):
        r = old.get(s["ccn"]) or {"ccn": s["ccn"], "name": s["name"], "domain": "", "source": "", "confidence": "", "alias": "", "note": ""}
        d = dolt.get(s["ccn"])
        if not r["domain"] and d and (d["homepage_url"] or "").strip():
            hp, cm = host(d["homepage_url"]), host(d["chargemaster_url"] or "")
            # homepage and price page on the same host = consistent record; otherwise lower confidence
            r.update(domain=hp, source="dolthub homepage_url", confidence="high" if hp == cm else "medium")
        if not r["domain"]:
            m = hifld_match(hgi[s["ccn"]], hifld)
            if m:
                r.update(domain=host(m[1]["WEBSITE"]), source=f"hifld WEBSITE ({m[2]}, name score {m[0]:.0f})",
                         confidence="medium" if m[2] == "phone" or m[0] >= 85 else "low")
        rows.append(r)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["ccn", "name", "domain", "source", "confidence", "alias", "note"])
        w.writeheader()
        w.writerows(rows)
    print(Counter((r["source"] or "none", r["confidence"]) for r in rows))


def hifld_rows():
    """HIFLD Open hospitals (2018-2020 vintage) via an ArcGIS mirror; only rows with a WEBSITE."""
    cache = RAW / "hifld_hospitals.json"
    if not cache.exists():
        api = "https://services.arcgis.com/XG15cJAlne2vxtgt/ArcGIS/rest/services/Hospitals_hifld/FeatureServer/0/query"
        rows, off = [], 0
        while True:
            got = requests.get(api, params={"where": "1=1", "outFields": "NAME,CITY,STATE,ZIP,TELEPHONE,WEBSITE", "returnGeometry": "false",
                                            "resultOffset": off, "resultRecordCount": 2000, "f": "json"}, timeout=120).json()["features"]
            rows += [g["attributes"] for g in got]
            off += 2000
            if len(got) < 2000:
                break
        cache.write_text(json.dumps(rows))
    return [r for r in json.loads(cache.read_text()) if "." in (r["WEBSITE"] or "")]


def digits(s):
    return "".join(c for c in s or "" if c.isdigit())[-10:]


def hifld_match(h, hifld):
    """Same state; phone match accepted at name score >= 50, ZIP match at >= 70, state-only at >= 90. Returns (score, row, key) or None."""
    from rapidfuzz import fuzz
    best = None
    for r in hifld:
        if r["STATE"] != h["State"]:
            continue
        sc = fuzz.token_sort_ratio(h["Facility Name"].lower(), r["NAME"].lower())
        key = "phone" if digits(r["TELEPHONE"]) == digits(h["Telephone Number"]) else "zip" if r["ZIP"] == h["ZIP Code"][:5] else "state"
        if sc >= {"phone": 50, "zip": 70, "state": 90}[key] and (best is None or sc > best[0]):
            best = (sc, r, key)
    return best


def strat_prop(y, strata, sizes):
    """Stratified proportion with FPC. y, strata: per sampled unit; sizes: {stratum: N_h}.
    Returns (p, se, wilson 95% CI on the design effective n)."""
    tot = sum(sizes.values())
    p = v = 0.0
    for h, N_h in sizes.items():
        ys = [a for a, b in zip(y, strata) if b == h]
        if not ys:
            continue
        n_h, W = len(ys), N_h / tot
        ph = sum(ys) / n_h
        p += W * ph
        v += W * W * (1 - n_h / N_h) * ph * (1 - ph) / max(n_h - 1, 1)
    neff = p * (1 - p) / v if v > 0 else len(y)
    z = 1.96
    c, half = (p + z * z / (2 * neff)) / (1 + z * z / neff), z * math.sqrt(p * (1 - p) / neff + z * z / (4 * neff * neff)) / (1 + z * z / neff)
    return p, math.sqrt(v), (max(0.0, c - half), min(1.0, c + half))


def summary():
    """Funnel, hospital-level populated shares with stratified 95% CIs, pooled row shares, defects by system (domain)."""
    import re
    smp = {r["ccn"]: r for r in csv.DictReader(open(NAT / "sample.csv", encoding="utf-8"))}
    cen = {r["ccn"]: r for r in csv.DictReader(open(NAT / "census.csv", encoding="utf-8"))}
    sizes = {r["stratum"]: int(r["N_h"]) for r in smp.values()}
    f = lambda v: float(v) if v not in ("", None) else 0.0
    full = lambda r: set(r["fields_present"].split("|")) >= {"median_amount", "10th_percentile", "90th_percentile", "count"}
    stages = {"sampled": lambda r: True, "domain found": lambda r: r["domain"] != "",
              "index ok": lambda r: r["index_status"].startswith("ok"), "matched to an mrf-url": lambda r: r["mrf_url"] != "",
              "parseable": lambda r: r["sample_n"] != "", "fields present": lambda r: r["sample_n"] != "" and full(r),
              "populated (>10% of payer rows)": lambda r: f(r["median_share"]) > 0.1}
    rs = [cen[c] for c in smp]
    st = [smp[c]["stratum"] for c in smp]
    out = {"funnel": {k: sum(map(g, rs)) for k, g in stages.items()}}
    resp = [i for i, r in enumerate(rs) if r["sample_n"]]
    for name, key in (("all rows", "median_share"), ("pct/alg rows", "req_median_share")):
        y = [int(f(r[key]) > 0.1) for r in rs]
        for base, idx in (("all sampled (non-response = not populated)", range(len(rs))), ("parseable responders", resp)):
            p, se, ci = strat_prop([y[i] for i in idx], [st[i] for i in idx], sizes)
            out[f"populated share | {name} | {base}"] = {"k": sum(y[i] for i in idx), "n": len(idx), "p": round(p, 4), "se": round(se, 4),
                                                          "ci95": [round(ci[0], 4), round(ci[1], 4)]}
    seen, tot = set(), Counter()
    for r in rs:
        if r["sample_n"] and r["mrf_url"] not in seen:
            seen.add(r["mrf_url"])
            tot["rows"] += int(r["sample_n"])
            tot["populated"] += round(f(r["median_share"]) * int(r["sample_n"]))
            tot["req_rows"] += int(f(r["req_rows"]))
            tot["req_populated"] += round(f(r["req_median_share"]) * f(r["req_rows"]))
    out["pooled rows (unique files)"] = {**tot, "files": len(seen), "share": round(tot["populated"] / max(tot["rows"], 1), 4),
                                         "req_share": round(tot["req_populated"] / max(tot["req_rows"], 1), 4)}
    out["index failures by status"] = Counter(re.sub(r" \[.*", "", r["index_status"]) for r in rs if not r["mrf_url"]).most_common()
    defects = Counter()
    for r in rs:
        for d in filter(None, re.split(r"; (?!served)", r["defects"])):
            defects[r["domain"], re.sub(r"(?<![/\d])\d+(?=\s*rows)|\b\d{4}-\d\d-\d\d\b", "#", d.split(" with CCNs")[0])] += 1
    out["top defects (domain, defect, hospitals)"] = [[*k, n] for k, n in defects.most_common(25)]
    (NAT / "summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    {"sample": sample, "domains": domains, "summary": summary}[sys.argv[1]]()
