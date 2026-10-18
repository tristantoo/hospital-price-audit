import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import hpt  # noqa: E402

ATT = '"To the best of its knowledge and belief, this hospital has included ... formula."'


def test_index_and_urldefense():
    txt = ("Location-name: VCU Health Tappahannock Hospital\nsource-page-url: https://x.org/p\n"
           "mrf-url: https://urldefense.com/v3/__https:/vcuhealth.pt.panaceainc.com/MRFDownload/vcuhealth/tapp__;!!Jq!abc$\n"
           "contact-name: J\ncontact-email: j@x.org\nlocation-name: B\nmrf-url: https://b.org/f.csv\n")
    e = hpt.parse_index(txt)
    assert [x["location-name"] for x in e] == ["VCU Health Tappahannock Hospital", "B"]
    assert hpt.unwrap_urldefense(e[0]["mrf-url"]) == ("https://vcuhealth.pt.panaceainc.com/MRFDownload/vcuhealth/tapp", True)
    assert hpt.unwrap_urldefense("https://b.org/f.csv") == ("https://b.org/f.csv", False)


def test_csv_tall():
    csv_text = (f"hospital_name,last_updated_on,version,attester_name,{ATT}\nH,2026-04-01,3.0.0,A,true\n"
                "description,code | 1,setting,payer_name,plan_name,standard_charge | negotiated_dollar,"
                "standard_charge | negotiated_percentage,median_amount,10th_percentile,90th_percentile,count\n"
                "MRI,70551,outpatient,Aetna,PPO,400,,380,250,500,42\n"
                "MRI,70551,outpatient,Cigna,HMO,,85,900,100,1200,1 through 10\n"
                "MRI,70551,outpatient,,,,,,,,\n")  # gross-only row: not a payer row
    meta, st = hpt.sample_csv(io.StringIO(csv_text))
    assert meta["format"] == "csv_tall" and meta["version"] == "3.0.0" and meta["attestation"] == "true"
    assert meta["fields"] == list(hpt.ALLOWED)
    assert (st.n, st.med, st.req, st.req_med, st.band_n, st.band_out) == (2, 2, 1, 1, 1, 0)
    assert st.counts == {"11-99": 1, "1 through 10": 1}


def test_csv_wide():
    csv_text = ("hospital_name,last_updated_on,version\nH,1/1/2025,2.2.0\n"
                "description,standard_charge|Aetna|PPO|negotiated_dollar,median_amount|Aetna|PPO,"
                "10th_percentile|Aetna|PPO,90th_percentile|Aetna|PPO,count|Aetna|PPO,standard_charge|Cigna|HMO|negotiated_dollar\n"
                "X,100,,,,,50\nY,700,90,80,95,12,\n")
    meta, st = hpt.sample_csv(io.StringIO(csv_text))
    assert meta["format"] == "csv_wide" and meta["attestation"] == "absent"
    assert (st.n, st.med, st.band_n, st.band_out) == (3, 1, 1, 1)  # 700 lies above P90=95


def test_json():
    doc = {"version": "3.0.0", "last_updated_on": "2026-04-01", "attestation": {"confirm_attestation": True, "attester_name": "A"},
           "standard_charge_information": [{"description": "MRI", "code_information": [{"code": "70551"}], "standard_charges": [
               {"setting": "outpatient", "payers_information": [
                   {"payer_name": "A", "plan_name": "P", "standard_charge_dollar": 10, "median_amount": 12,
                    "10th_percentile": 11, "90th_percentile": 13, "count": "0"},  # count 0: not populated
                   {"payer_name": "B", "plan_name": "Q", "standard_charge_percentage": 50}]}]}]}
    raw = json.dumps(doc).encode()
    meta = hpt.json_header(io.BytesIO(raw))
    jm, st = hpt.sample_json(io.BytesIO(raw))
    assert meta == {"version": "3.0.0", "last_updated_on": "2026-04-01", "attestation": "true", "attester_name": True}
    assert (jm["fields"], st.n, st.med_any, st.med_zero_count, st.med, st.req, st.band_n) == (list(hpt.ALLOWED), 2, 1, 1, 0, 1, 0)


def test_dispersion_bins():
    assert [hpt.n_bin(c) for c in ("1 through 10", "7", "11", "30", "31", "150", "151", "0", "")] == [
        "1 through 10", "1 through 10", "11-30", "11-30", "31-150", "31-150", ">150", "missing/0/other", "missing/0/other"]
    assert abs(hpt.dispersion(100, 100 * 2.718281828 ** 2.563) - 1.0) < 1e-6
    assert hpt.dispersion(0, 5) is None and hpt.dispersion(None, 5) is None


def test_zip_stream_and_cap():
    import zipfile
    import census
    csv_text = (f"hospital_name,last_updated_on,version\nH,2026-04-01,3.0.0\n"
                "description,code | 1,code | 1 | type,setting,payer_name,plan_name,standard_charge | negotiated_dollar,"
                "standard_charge | methodology,median_amount,10th_percentile,90th_percentile,count\n"
                + "DRG 470,470,MS-DRG,inpatient,Aetna,PPO,20000,case rate,21000,15000,30000,42\n" * 5000)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readme.txt", "x")
        z.writestr("prices.csv", csv_text)
        z.writestr("__MACOSX/._prices.csv", "y" * 300)  # trailing member after the data (seen in the wild)
    raw = b.getvalue()
    big = io.BytesIO()
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:  # 60:1 ratio: stream ends with input still unconsumed
        z.writestr("p.csv", "a,b\n" * 6_000_000)
        z.writestr("__MACOSX/._p.csv", "y" * 300)
    assert len(io.BufferedReader(census.Inflate(io.BytesIO(big.getvalue())), 1 << 20).read()) == 24_000_000
    meta, st = census.parse(io.BufferedReader(io.BytesIO(raw)), lambda: io.BytesIO(raw))
    assert meta["zipped"] and meta["format"] == "csv_tall" and st.n == 5000
    assert st.cells[0][5:9] == (False, "MS-DRG", "inpatient", "")  # (pct/alg row?, code_type, setting, billing_class)
    _, st2 = census.parse(io.BufferedReader(io.BytesIO(raw[: len(raw) // 2])), lambda: io.BytesIO(raw))  # truncated archive
    assert 0 < st2.n < 5000
    census.CAP, cap = 100_000, census.CAP
    try:
        tee = census.Tee(io.BytesIO(b"x" * 300_000), io.BytesIO())
        assert len(io.BufferedReader(tee, 1 << 14).read()) < 120_000
    finally:
        census.CAP = cap

    class Closed(io.RawIOBase):  # a connection the watchdog closed after the deadline
        def read(self, n):
            import time
            time.sleep(0.1)  # the read outlives the deadline, then the socket is closed under it
            raise OSError("closed")
    census.TIME_CAP, tc = 0.05, census.TIME_CAP
    try:
        tee = census.Tee(Closed(), io.BytesIO())
        assert tee.readinto(bytearray(10)) == 0 and tee.timed_out
    finally:
        census.TIME_CAP = tc
    tee = census.Tee(Closed(), io.BytesIO())
    tee.n = 5  # broken mid-file (before the deadline): truncated sample, not an error
    assert tee.readinto(bytearray(10)) == 0 and tee.broken and not tee.timed_out


def test_sampling_and_design_ci():
    import national
    a = national.allocate({"A": 2000, "B": 1000, "C": 7}, 300)
    assert sum(a.values()) == 300 and a["A"] == 199 and a["B"] == 100 and a["C"] == 1
    p, se, (lo, hi) = national.strat_prop([1, 0, 0, 0, 1, 0], ["A", "A", "A", "B", "B", "B"], {"A": 100, "B": 100})
    assert abs(p - 1 / 3) < 1e-9 and se > 0 and lo < p < hi


def test_unit_match():
    import dispersion
    assert dispersion.unit_match("APR-DRG", "") == "per-case (DRG/case rate)"
    assert dispersion.unit_match("CPT", "fee schedule") == "per-service (CPT/HCPCS fee schedule)"
    assert dispersion.unit_match("RC", "per diem") == "unmatched"
