"""Write site/data.json from the national and Virginia scorecards. uv run python src/site.py [--to DIR]"""
import csv
import json
import shutil
import sys
from pathlib import Path

from scorecard import AS_OF, CHECKS

ROOT = Path(__file__).resolve().parents[1]


def load(d, label):
    state = {r["ccn"]: r["state"] for r in csv.DictReader(open(ROOT / d / "sample.csv", encoding="utf-8"))} if (ROOT / d / "sample.csv").exists() else {}
    rows = [{"name": r["name"].title(), "city": r["city"].title(), "state": state.get(r["ccn"], "VA"), "domain": r["domain"],
             "set": label, "clean": r["clean"] == "1", "checks": {n: (None if r[n] == "" else int(r[n])) for n, _ in CHECKS}}
            for r in csv.DictReader(open(ROOT / d / "scorecard.csv", encoding="utf-8"))]
    return rows, json.loads((ROOT / d / "scorecard_summary.json").read_text())


us, us_sum = load("data/national", "us")
va, va_sum = load("data/recon", "va")
retest = ROOT / "data/national/retest.json"
out = {"as_of": str(AS_OF), "checks": [{"id": n, "required": bool(q)} for n, q in CHECKS],
       "retest": json.loads(retest.read_text()) if retest.exists() else None,
       "summary": {"us": us_sum, "va": va_sum}, "hospitals": us + va}
(ROOT / "site").mkdir(exist_ok=True)
(ROOT / "site/data.json").write_text(json.dumps(out, separators=(",", ":")))
print(len(out["hospitals"]), "hospitals ->", ROOT / "site/data.json")

# --to DIR: also write a standalone page (site/index.html is a fragment; the artifact host adds the document shell)
if "--to" in sys.argv:
    to = Path(sys.argv[sys.argv.index("--to") + 1])
    to.mkdir(parents=True, exist_ok=True)
    head, body = (ROOT / "site/index.html").read_text(encoding="utf-8").split("<main>", 1)
    (to / "index.html").write_text('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                                   f'{head}</head>\n<body>\n<main>{body}</body>\n</html>\n', encoding="utf-8")
    shutil.copy(ROOT / "site/data.json", to / "data.json")
    print("standalone page ->", to)
