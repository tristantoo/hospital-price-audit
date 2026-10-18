"""Parsing for CMS hospital price transparency files: cms-hpt.txt index + bounded MRF sampling (v2.x/v3.0)."""
import csv
import math
import re
from collections import Counter
from urllib.parse import unquote

import ijson

ROW_CAP = 200_000  # data rows (CSV) or payer rows (JSON) read per MRF
ALLOWED = ("median_amount", "10th_percentile", "90th_percentile", "count")
UNIT_KEYS = ("code_type", "setting", "billing_class", "methodology", "code", "description")


def unwrap_urldefense(url):
    """Proofpoint v3 wraps as https://urldefense.com/v3/__<url>__;<sig>$ (and collapses '//' to '/')."""
    m = re.match(r"https?://urldefense\.com/v3/__(.+?)__;", url)
    if not m:
        return url, False
    inner = re.sub(r"^(https?):/(?!/)", r"\1://", m.group(1))
    return unquote(inner), True


def parse_index(text):
    """cms-hpt.txt -> list of dicts. A new entry starts at each location-name (keys case-insensitive)."""
    entries = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        if k == "location-name":
            entries.append({})
        if entries and k in ("location-name", "source-page-url", "mrf-url", "contact-name", "contact-email"):
            entries[-1][k] = v.strip()
    return entries


def norm(h):
    return re.sub(r"\s*\|\s*", "|", (h or "").strip().lower())


def num(x):
    try:
        return float(str(x).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def blank(x):
    return x is None or str(x).strip() == ""


class Stats:
    """Accumulates population stats over normalized payer rows."""

    def __init__(self):
        self.n = self.med_any = self.med = self.med_zero_count = self.req = self.req_med = self.band_n = self.band_out = 0
        self.counts = Counter()
        self.examples = []
        self.cells = []  # populated rows: (count, p10, p90, negotiated $, median, pct/alg row?, *UNIT_KEYS) for dispersion + units checks

    def add(self, r):
        self.n += 1
        med = num(r.get("median_amount"))
        c = str(r.get("count") or "").strip()
        has_any = med not in (None, 0.0)
        zero = num(c) == 0  # spec: count "0" means no remittances, so allowed amounts must not be encoded
        has_med = has_any and not zero  # "populated" = a nonzero median backed by a nonzero count
        self.med_any += has_any
        self.med_zero_count += has_any and zero
        self.med += has_med
        if not blank(r.get("neg_pct")) or not blank(r.get("neg_alg")):  # rows where CMS requires allowed amounts
            self.req += 1
            self.req_med += has_med
        if c:
            n = num(c)
            if n is None:
                key = c.lower()  # e.g. the CMS small-count mask "1 through 10"
            elif n == 0:
                key = "0"
            elif n < 11:
                key = "1-10 unmasked"  # spec says encode as "1 through 10"
            else:
                key = "11-99" if n < 100 else "100-999" if n < 1000 else "1000+"
            self.counts[key] += 1
        d, p10, p90 = num(r.get("neg_dollar")), num(r.get("10th_percentile")), num(r.get("90th_percentile"))
        if has_med and None not in (d, p10, p90) and p90 > 0:
            self.band_n += 1
            self.band_out += d < p10 or d > p90
        if has_med:
            self.cells.append((c.lower(), p10, p90, d, med, not blank(r.get("neg_pct")) or not blank(r.get("neg_alg")),
                               *(str(r.get(k) or "")[:40] for k in UNIT_KEYS)))
        if has_med and len(self.examples) < 5:
            self.examples.append({k: r.get(k) for k in ("description", "code", "setting", "payer", "plan", "neg_dollar",
                                                        "neg_pct", "neg_alg", "median_amount", "10th_percentile", "90th_percentile", "count")})


def n_bin(c):
    """Count-of-allowed-amounts bin. Unmasked 1-10 is folded into the masked bin."""
    n = num(c)
    if c == "1 through 10" or (n is not None and 1 <= n <= 10):
        return "1 through 10"
    if n is None or n == 0:
        return "missing/0/other"
    return "11-30" if n <= 30 else "31-150" if n <= 150 else ">150"


def dispersion(p10, p90):
    """s = log(P90/P10)/2.563: the lognormal sigma implied by the 10-90 spread. None if not computable."""
    return math.log(p90 / p10) / 2.563 if p10 and p90 and p10 > 0 and p90 >= p10 else None


def sample_csv(lines, cap=ROW_CAP):
    """lines: iterable of text lines. Returns (meta dict, Stats)."""
    rd = csv.reader(lines)
    h1 = [norm(x) for x in next(rd)]
    v1 = next(rd)
    cols = [norm(x) for x in next(rd)]
    meta = {k: (v1[h1.index(k)].strip() if k in h1 and h1.index(k) < len(v1) else "") for k in ("version", "last_updated_on")}
    att = next((i for i, h in enumerate(h1) if h.startswith("to the best of its knowledge")), None)
    meta["attestation"] = "absent" if att is None else (v1[att].strip() if att < len(v1) else "") or "blank"
    meta["attester_name"] = "attester_name" in h1
    st = Stats()
    if "payer_name" in cols:
        meta["format"] = "csv_tall"
        meta["fields"] = [f for f in ALLOWED if f in cols]
        ix = {c: i for i, c in enumerate(cols)}
        g = {"payer": "payer_name", "plan": "plan_name", "neg_dollar": "standard_charge|negotiated_dollar", "methodology": "standard_charge|methodology",
             "neg_pct": "standard_charge|negotiated_percentage", "neg_alg": "standard_charge|negotiated_algorithm",
             **{f: f for f in ALLOWED}}
        groups = [{k: ix.get(v) for k, v in g.items()}]
        rowkey = lambda row: bool(row[ix["payer_name"]].strip()) if ix["payer_name"] < len(row) else False
    else:
        meta["format"] = "csv_wide"
        groups = {}
        for i, c in enumerate(cols):
            p = c.split("|")
            if p[0] == "standard_charge" and len(p) == 4:
                groups.setdefault((p[1], p[2]), {})[{"negotiated_dollar": "neg_dollar", "negotiated_percentage": "neg_pct",
                                                    "negotiated_algorithm": "neg_alg"}.get(p[3], p[3])] = i
            elif p[0] in ALLOWED and len(p) == 3:
                groups.setdefault((p[1], p[2]), {})[p[0]] = i
        meta["fields"] = [f for f in ALLOWED if any(f in g for g in groups.values())]
        for (payer, plan), g in groups.items():
            g["payer_name"], g["plan_name"] = payer, plan
        groups = list(groups.values())
        rowkey = None
    ci = {c: i for i, c in enumerate(cols)}
    n = -1
    for n, row in enumerate(rd):
        if n >= cap:
            break
        get = lambda i: row[i].strip() if i is not None and isinstance(i, int) and i < len(row) else None
        base = {"description": (get(ci.get("description")) or "")[:80], "code": get(ci.get("code|1")), "setting": get(ci.get("setting")),
                "code_type": get(ci.get("code|1|type")), "billing_class": get(ci.get("billing_class"))}
        for g in groups:
            r = {**base, **{k: get(i) for k, i in g.items() if k not in ("payer_name", "plan_name")}}
            if rowkey is None:  # wide: a payer row exists where any negotiated charge is encoded
                if all(blank(r.get(k)) for k in ("neg_dollar", "neg_pct", "neg_alg")):
                    continue
                r["payer"], r["plan"] = g["payer_name"], g["plan_name"]
            elif not rowkey(row):
                continue
            st.add(r)
    meta["rows_read"] = min(n + 1, cap)
    return meta, st


def json_header(f):
    """Top-level scalars + attestation block, read until standard_charge_information begins."""
    meta = {}
    try:
        for prefix, event, value in ijson.parse(f):
            if prefix == "standard_charge_information":
                break
            if prefix in ("version", "last_updated_on") and event in ("string", "number"):
                meta[prefix] = str(value)
            elif prefix in ("attestation.confirm_attestation", "affirmation.confirm_affirmation"):
                meta["attestation"] = str(value).lower()
            elif prefix == "attestation.attester_name":
                meta["attester_name"] = True
    except ijson.common.IncompleteJSONError:
        pass
    return meta


def sample_json(f, cap=ROW_CAP):
    """f: binary file positioned at start. Returns (meta, Stats). Truncated files end the sample quietly."""
    st, keys, n = Stats(), set(), 0
    try:
        for item in ijson.items(f, "standard_charge_information.item"):
            ci = (item.get("code_information") or [{}])[0]
            for sc in item.get("standard_charges") or []:
                for p in sc.get("payers_information") or []:
                    keys |= p.keys()
                    st.add({"description": (item.get("description") or "")[:80], "code": ci.get("code"), "setting": sc.get("setting"),
                            "code_type": ci.get("type"), "billing_class": sc.get("billing_class"), "methodology": p.get("methodology"),
                            "payer": p.get("payer_name"), "plan": p.get("plan_name"), "neg_dollar": p.get("standard_charge_dollar"),
                            "neg_pct": p.get("standard_charge_percentage"), "neg_alg": p.get("standard_charge_algorithm"),
                            **{k: p.get(k) for k in ALLOWED}})
                    n += 1
            if n >= cap:
                break
    except ijson.common.IncompleteJSONError:
        pass
    return {"format": "json", "fields": [k for k in ALLOWED if k in keys], "rows_read": n}, st
