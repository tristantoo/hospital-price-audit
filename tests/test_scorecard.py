import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scorecard import grade  # noqa: E402

BASE = dict(index_status="ok", mrf_url="https://h.org/f.csv", http="200", format="csv_tall", defects="", sample_n="1000",
            version="3.0.0", last_updated_on="2026-04-01", attestation="TRUE",
            fields_present="median_amount|10th_percentile|90th_percentile|count", req_rows="500", req_median_share="0.5", median_share="0.2")


def test_clean_file_passes_everything():
    assert all(v == 1 for v in grade(BASE).values())


def test_blocked_index_fails_but_404_is_unassessable():
    blocked = grade({**BASE, "index_status": "fail [a.org: 403 (UA retry); www.a.org: 403 (UA retry)]", "mrf_url": "", "sample_n": ""})
    assert blocked["index_valid"] == 0 and blocked["location_listed"] is None
    assert grade({**BASE, "index_status": "fail [a.org: 404; www.a.org: 404]"})["index_valid"] is None
    assert grade({**BASE, "index_status": "fail [a.org: 403 (UA retry); www.a.org: ReadTimeout]"})["index_valid"] is None


def test_matcher_miss_is_unassessable_empty_index_fails():
    assert grade({**BASE, "index_status": "ok but no matching location entry", "mrf_url": ""})["location_listed"] is None
    assert grade({**BASE, "index_status": "ok but no location entries", "mrf_url": ""})["location_listed"] == 0


def test_content_defects():
    assert grade({**BASE, "version": "V3.0.0"})["template_v3"] == 1
    g = grade({**BASE, "version": "2.0.0", "last_updated_on": "2025-01-28", "attestation": "", "req_median_share": "0.05",
               "defects": "MRF served as .zip (CMS requires CSV or JSON); 37 rows encode allowed amounts with count=0 (spec: leave blank)"})
    assert (g["template_v3"], g["updated_12mo"], g["attested"], g["fields_populated"], g["open_format"], g["no_count0_amounts"]) == (0,) * 6
    assert grade({**BASE, "fields_present": "count"})["fields_populated"] == 0
    assert grade({**BASE, "req_rows": "0", "median_share": "0.3"})["fields_populated"] == 1
