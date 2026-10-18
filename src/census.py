"""Census of hospital MRFs for the 2026 allowed-amount fields.
Virginia (default, hand-curated DOMAINS): uv run python src/census.py
Any frame: uv run python src/census.py --frame data/national/domains.csv --out data/national --raw data/raw/national"""
import argparse
import csv
import hashlib
import io
import json
import os
import pickle
import struct
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

sys.path.insert(0, str(Path(__file__).parent))
import hpt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/recon"
BUDGET, CAP = 12 * 1024**3, 300 * 1024**2  # raw bytes kept on disk; bytes downloaded per MRF
TIME_CAP = 900  # seconds per MRF download: some servers trickle bytes forever under the per-read timeout
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
FEDERAL = {"49001F", "49006F", "49008F", "49010F", "49011F"}  # VA/DoD: exempt from 45 CFR 180 (federally owned)

# CCN -> domain, assembled by hand from system affiliations (see findings.md).
DOMAINS = {
    "sentara.com": "490004 490007 490013 490044 490046 490057 490066 490077 490093 490113 490119",
    "inova.org": "490040 490043 490063 490101 490122",
    "hcavirginia.com": "490020 490048 490107 490110 490112 490116 490118 490126 490141 490145",
    "dominionhospital.com": "494023",
    "bonsecours.com": "490017 490041 490059 490067 490069 490092 490094 490097 490136 490148 491308",
    "carilionclinic.org": "490024 490042 490089 490117 491302 491304",
    "riversideonline.com": "490037 490052 490130 490143",
    "balladhealth.org": "490002 490038 490053 490114 491303 491309",
    "vcuhealth.org": "490032 490084 490098",
    "uvahealth.com": "490009 490019 490045 490144",
    "valleyhealthlink.com": "490005 490033 491305 491307",
    "centrahealth.com": "490021 490088 490090",
    "marywashingtonhealthcare.com": "490022 490140",
    "fauquierhealth.org": "490023", "clinchvalleyhealth.com": "490060", "wcch.org": "490111", "tcrh.org": "490115",
    "sovahhealth.com": "490075", "augustahealth.com": "490018", "chesapeakeregional.com": "490120",
    "virginiahospitalcenter.com": "490050", "chkd.org": "493301", "bathhospital.org": "491300", "bgh.org": "490127",
    "dbhds.virginia.gov": "490104 494010 494017 494021 494029 494033",
    "poplarsprings.com": "494022", "vbpcweb.com": "494025", "pavilionwp.com": "494032", "cumberlandhospital.com": "493300",
}
CCN_DOMAIN = {c: d for d, cs in DOMAINS.items() for c in cs.split()}
# Renamed / legal-entity names that fuzzy matching cannot bridge (verified by hand).
ALIAS = {
    "490024": "Carilion Roanoke Memorial Hospital", "491304": "Carilion Rockbridge Community Hospital",
    "490020": "TRICITIES HOSPITAL", "490112": "CJW Medical Center-Chippenham Hospital Campus",
    "490037": "Shore Health Services, Inc.", "490052": "Riverside Hospital, Inc.",
    "490130": "Riverside Middle Peninsula Hospital, Inc.", "490143": "Doctors' Hospital of Williamsburg",
    "490032": "VCU Medical Center", "490009": "UVA Health Medical Center", "490136": "St Francis Medical Center",
    "490067": "Southside Regional Medical Center", "490097": "Southern Virginia Medical Center",
    "490092": "Southampton Medical Center", "490094": "Richmond Community Hospital", "490069": "Memorial Regional Hospital",
    "490059": "St Mary's Hospital", "490017": "Maryview Hospital", "490118": "HENRICO DOCTORS HOSPITAL", "490048": "LEWISGALE MEDICAL CENTER",
    "490075": "Sovah Health - Danville", "490060": "Clinch Valley Health", "490023": "Fauquier Health",
    "494032": "the pavilion", "493301": "Children's Hospital of The King's Daughters", "490120": "Chesapeake General Hospital",
}
S = requests.Session()
BOM_WS = bytes([0xEF, 0xBB, 0xBF, 32, 13, 10, 9])  # BOM + whitespace


def get(url, **kw):
    """GET; on 403/406 (client refused) retry once with a browser User-Agent. Returns (response, ua_retry_used)."""
    r = S.get(url, timeout=(15, 120), **kw)
    if r.status_code in (403, 406):
        r.close()
        return S.get(url, timeout=(15, 120), headers={"User-Agent": UA}, **kw), True
    return r, False


def fetch_index(domain):
    (RAW / "index").mkdir(parents=True, exist_ok=True)
    res = {"status": "fail", "attempts": []}
    # subdomain homepages (healthcare.x.org): also try the registrable domain; never a bare government suffix (dbhds.virginia.gov)
    parent = domain if domain.endswith(".gov") else ".".join(domain.split(".")[-2:])
    for host in dict.fromkeys((domain, "www." + domain, parent, "www." + parent)):
        try:
            r, ua = get(f"https://{host}/cms-hpt.txt")
        except requests.RequestException as e:
            res["attempts"].append(f"{host}: {type(e).__name__}")
            continue
        res["attempts"].append(f"{host}: {r.status_code}{' (UA retry)' if ua else ''}")
        if r.ok and "mrf-url" in r.text.lower():
            (RAW / "index" / f"{domain}.txt").write_text(r.text, encoding="utf-8")
            return {**res, "status": "ok", "url": r.url, "ua": ua, "entries": hpt.parse_index(r.text)}
    return res


class Tee(io.RawIOBase):
    """Streams the HTTP body to a raw file as it is parsed, so we only keep what we read."""

    def __init__(self, src, dst):
        self.src, self.dst, self.n, self.t0, self.timed_out, self.broken = src, dst, 0, time.monotonic(), False, False

    def readable(self):
        return True

    def readinto(self, b):
        self.timed_out = time.monotonic() - self.t0 > TIME_CAP
        if self.n >= CAP or self.timed_out:  # per-file caps: report EOF, the parsers treat it as a truncated file
            return 0
        try:
            data = self.src.read(len(b))
        except Exception:  # watchdog closed a stalled connection, or the server broke it mid-file: keep what we have
            self.timed_out = time.monotonic() - self.t0 > TIME_CAP
            self.broken = not self.timed_out
            if self.broken and not self.n:
                raise
            return 0
        self.dst.write(data)
        self.n += len(data)
        b[: len(data)] = data
        return len(data)


class Inflate(io.RawIOBase):
    """Streams the first .csv/.json member out of a zip from a (possibly truncated) byte stream, via local headers."""

    def __init__(self, src):
        self.src, self.buf = src, b""
        while True:
            h = src.read(30)
            if len(h) < 30 or h[:4] != b"PK":
                raise ValueError("zip has no readable .csv/.json member")
            _, _, flags, method, _, _, _, csize, _, nlen, xlen = struct.unpack("<4sHHHHHIIIHH", h)
            name = src.read(nlen).decode("utf-8", "replace")
            src.read(xlen)
            if name.lower().endswith((".csv", ".json")):
                break
            if flags & 8:
                raise ValueError(f"zip member {name} has no size in its local header")
            src.read(csize)
        if method != 8:
            raise ValueError(f"zip compression method {method}")
        self.z = zlib.decompressobj(-15)

    def readable(self):
        return True

    def readinto(self, b):
        while not self.buf:
            if self.z.eof:  # bytes after the stream end (unconsumed_tail/next member) are not ours
                return 0
            data = self.z.unconsumed_tail or self.src.read(1 << 16)
            if not data:
                return 0
            self.buf = self.z.decompress(data, 1 << 20)
        n = min(len(b), len(self.buf))
        b[:n], self.buf = self.buf[:n], self.buf[n:]
        return n


def parse(buf, reopen):
    """Dispatch on the first bytes. JSON: body pass on the live stream, header pass on the saved prefix."""
    if buf.peek(4)[:2] == b"PK":
        meta, st = parse(io.BufferedReader(Inflate(buf), 1 << 20), lambda: io.BufferedReader(Inflate(reopen()), 1 << 20))
        return {**meta, "zipped": True}, st
    head = buf.peek(64)[:64].lstrip(BOM_WS)
    if head.startswith(b"{"):
        bom = buf.peek(3)[:3] == BOM_WS[:3]  # ijson chokes on a UTF-8 BOM
        if bom:
            buf.read(3)
        jm, st = hpt.sample_json(buf)
        f = reopen()
        if bom:
            f.read(3)
        meta = hpt.json_header(f)
        return {**meta, **jm}, st
    if head[:1] == b"<":
        return {"format": "html (not an MRF)"}, None
    return hpt.sample_csv(io.TextIOWrapper(buf, encoding="utf-8-sig", errors="replace", newline=""))


def fetch_mrf(url):
    """Sample one MRF. The result (incl. Stats) is pickled per URL so raw prefixes can be deleted to stay under BUDGET."""
    url, wrapped = hpt.unwrap_urldefense(url)
    done = RAW / "done" / (raw_path(url).stem + ".pkl")
    if done.exists():
        return pickle.loads(done.read_bytes())
    rec = {"defects": ["mrf-url wrapped in Proofpoint urldefense link (unwrapped to fetch)"] if wrapped else []}
    try:
        r, ua = get(url, stream=True)
    except requests.RequestException as e:
        return {**rec, "http": type(e).__name__}
    cd = r.headers.get("Content-Disposition", "")
    rec.update(http=r.status_code, size=r.headers.get("Content-Length", ""),
               filename=cd.split("filename=")[-1].split(";")[0].strip('"') if "filename=" in cd else "")
    if ua:
        rec["defects"].append("MRF 403/406 to plain client; served with browser UA")
    if not r.ok:
        r.close()
        return rec
    path = raw_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size:  # sample already on disk from an earlier run: re-parse, no download
            meta, st = parse_file(path)
        else:
            r.raw.decode_content = True
            # urllib3 read(n) blocks until n bytes arrive, so a trickling server never returns control: close it from a timer
            watchdog = threading.Timer(TIME_CAP + 5, r.close)
            watchdog.start()
            with open(path, "wb") as dst:
                tee = Tee(r.raw, dst)
                meta, st = parse(io.BufferedReader(tee, 1 << 20), lambda: (dst.flush(), open(path, "rb"))[1])
            meta["capped"] = "time" if tee.timed_out else "connection broken" if tee.broken else "bytes" if tee.n >= CAP else ""
    except Exception as e:  # malformed files are a finding, not a crash
        return {**rec, "format": f"parse error: {type(e).__name__}: {str(e)[:80]}"}
    finally:
        r.close()
        if "watchdog" in locals():
            watchdog.cancel()
    if meta.pop("zipped", False):
        rec["defects"].append("MRF served as .zip (CMS requires CSV or JSON)")
    rec = {**rec, **meta, "stats": st, "bytes_read": path.stat().st_size}
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_bytes(pickle.dumps(rec))
    if raw_bytes() > BUDGET - 4 * CAP:  # room for 4 in-flight downloads
        path.unlink()
        rec["raw_deleted"] = True
    return rec


def raw_bytes():
    return sum(e.stat().st_size for e in os.scandir(RAW / "mrf")) if (RAW / "mrf").exists() else 0


def raw_path(url):
    return RAW / "mrf" / (hashlib.sha1(url.encode()).hexdigest()[:12] + ".part")


def parse_file(path):
    """Re-parse a saved raw prefix (or full zip) from disk."""
    return parse(io.BufferedReader(io.FileIO(path), 1 << 20), lambda: open(path, "rb"))


def lu_date(s):
    for f in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%m-%d-%Y"):
        try:
            return datetime.strptime((s or "").strip()[:19], f).date()
        except ValueError:
            pass
    return None


def main():
    global RAW, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", help="CSV with ccn, domain[, alias]; default: Virginia via the DOMAINS map")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--raw", type=Path, default=RAW)
    a = ap.parse_args()
    hgi = list(csv.DictReader(open(RAW / "Hospital_General_Information.csv", encoding="utf-8-sig")))
    RAW, OUT = a.raw, a.out
    if a.frame:
        fr = {r["ccn"]: r for r in csv.DictReader(open(a.frame, encoding="utf-8"))}
        frame = [h for h in hgi if h["Facility ID"] in fr]
        dom, alias = {c: r["domain"] for c, r in fr.items()}, {c: r["alias"] for c, r in fr.items() if r.get("alias")}
    else:
        frame, dom, alias = [h for h in hgi if h["State"] == "VA"], CCN_DOMAIN, ALIAS
    with ThreadPoolExecutor(4) as pool:
        ds = sorted({dom[h["Facility ID"]] for h in frame if dom.get(h["Facility ID"])})
        idx = dict(zip(ds, pool.map(fetch_index, ds)))
    print({d: v["status"] for d, v in idx.items()}, flush=True)
    rows = []
    for h in frame:
        ccn = h["Facility ID"]
        row = {"ccn": ccn, "name": h["Facility Name"], "city": h["City/Town"], "type": h["Hospital Type"],
               "domain": dom.get(ccn, ""), "defects": []}
        if ccn in FEDERAL:
            row["index_status"] = "exempt (federal)"
            rows.append(row)
            continue
        if not row["domain"]:
            row["index_status"] = "no domain found"
            rows.append(row)
            continue
        ix = idx[row["domain"]]
        row["index_status"] = ix["status"] + ("" if ix["status"] == "ok" else f" [{'; '.join(ix['attempts'])}]")
        if ix["status"] == "ok" and not ix["entries"]:
            row["index_status"] = "ok but no location entries"
        elif ix["status"] == "ok":
            row["index_url"] = ix["url"]
            if ix["ua"]:
                row["defects"].append("cms-hpt.txt 403/406 to plain client; served with browser UA")
            target = alias.get(ccn, h["Facility Name"])
            # mean of set+sort ratios: set alone scores any subset name ("UVA Health Medical Center") as 100
            sc = lambda a, b: (fuzz.token_set_ratio(a, b, processor=default_process) + fuzz.token_sort_ratio(a, b, processor=default_process)) / 2
            scored = [(round(sc(target, e.get("location-name", "")), 1), e) for e in ix["entries"]]
            score, e = max(scored, key=lambda t: t[0])
            row["match_score"] = score
            row["match_method"] = "alias" if ccn in alias else "single entry" if len(scored) == 1 else "fuzzy"
            # a one-entry index on the hospital's own domain is its file whatever the label says
            if (score >= 70 or len(scored) == 1) and e.get("mrf-url"):
                row["location_name"], row["mrf_url"] = e["location-name"], e["mrf-url"]
            else:
                row["index_status"] = "ok but no matching location entry"
        rows.append(row)

    urls = list(dict.fromkeys(r["mrf_url"] for r in rows if r.get("mrf_url")))

    def fetch(u):
        m = fetch_mrf(u)
        print("done", len(urls), u[:100], m.get("http"), m.get("format"), flush=True)
        return m

    with ThreadPoolExecutor(4) as pool:
        mrfs = dict(zip(urls, pool.map(fetch, urls)))
    for row in rows:
        u = row.get("mrf_url")
        if not u:
            continue
        m = mrfs[u]
        st = m.get("stats")
        row["defects"] += m["defects"]
        row.update({k: m.get(k, "") for k in ("http", "size", "filename", "format", "capped", "version", "last_updated_on", "attestation")})
        row["fields_present"] = "|".join(m.get("fields", []))
        if st:
            row.update(sample_n=st.n, median_share=round(st.med / st.n, 4) if st.n else "", median_any_share=round(st.med_any / st.n, 4) if st.n else "",
                       req_rows=st.req, req_median_share=round(st.req_med / st.req, 4) if st.req else "",
                       count_dist=json.dumps(dict(st.counts.most_common(8))), band_n=st.band_n, band_outside=st.band_out,
                       examples=st.examples)
        if m.get("version") and not str(m["version"]).startswith("3"):
            row["defects"].append(f"template version {m['version']} (not v3.0)")
        d = lu_date(m.get("last_updated_on"))
        if m.get("last_updated_on") and d is None:
            row["defects"].append(f"unparseable last_updated_on '{m['last_updated_on']}'")
        elif d and d < datetime(2026, 1, 1).date():
            row["defects"].append(f"last_updated_on {d} predates 2026 rule")
        if str(m.get("attestation", "")).lower() not in ("true", ""):
            row["defects"].append(f"attestation={m.get('attestation')}")
        if m.get("format", "").startswith("html"):
            row["defects"].append("mrf-url returns HTML, not a file")
        if st and st.med_zero_count:
            row["defects"].append(f"{st.med_zero_count} rows encode allowed amounts with count=0 (spec: leave blank)")
        if st and st.counts.get("1-10 unmasked"):
            row["defects"].append("counts 1-10 encoded as numbers instead of '1 through 10'")
        if st and st.n and set(hpt.ALLOWED) - set(m.get("fields", [])):
            row["defects"].append("missing 2026 fields: " + ",".join(sorted(set(hpt.ALLOWED) - set(m.get("fields", [])))))
    shared = {}
    for row in rows:
        if row.get("mrf_url"):
            shared.setdefault(row["mrf_url"], []).append(row["ccn"])
    for row in rows:
        if len(shared.get(row.get("mrf_url"), [])) > 1:
            row["defects"].append(f"MRF shared with CCNs {','.join(c for c in shared[row['mrf_url']] if c != row['ccn'])}")

    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["ccn", "name", "city", "type", "domain", "index_status", "index_url", "location_name", "match_method", "match_score", "mrf_url",
            "http", "size", "filename", "format", "capped", "version", "last_updated_on", "attestation", "fields_present", "sample_n",
            "median_share", "median_any_share", "req_rows", "req_median_share", "count_dist", "band_n", "band_outside", "defects"]
    with open(OUT / "census.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({**row, "defects": "; ".join(row["defects"])})
    (OUT / "examples.json").write_text(json.dumps({r["ccn"]: r.get("examples", []) for r in rows if r.get("examples")}, indent=1, default=str))
    print("raw bytes on disk:", raw_bytes())


if __name__ == "__main__":
    main()
