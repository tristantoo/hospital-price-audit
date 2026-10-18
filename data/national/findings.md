# National findings: hospital allowed-amount fields (2026-10-17)

Source: `summary.json`, `census.csv`, `dispersion_summary.json`, `units_sample.json`. Each file was read from its start only (up to 300 MB).

## Design
- The frame is 4,397 acute-care and critical-access hospitals from CMS Hospital General Information. It excludes federal hospitals (VA, DoD, IHS).
- The sample is 300 hospitals, stratified by Census region × hospital type with proportional allocation (seed 20261018) and no replacement.
- The sample was drawn before any domain lookup, so non-response counts as a finding.
- Domains came from DoltHub (77), HIFLD (179) and hand resolution (44). The aliases and fixes are recorded per row in `domains.csv`.

## Funnel
300 sampled → 262 index ok → 251 matched to a price file → 237 parseable → 217 with all 4 fields → **27 populated** (fields filled on more than 10% of payer rows).

## Populated share (stratified estimate, Wilson 95% CI on the design-effective n)

| Rows counted | All 300 (non-response = not populated) | 237 parseable |
|---|---|---|
| All payer rows | **9.0% [6.4, 12.5]** | 11.5% [8.2, 15.9] |
| Percent/algorithm rows only (where CMS requires the fields) | **13.6% [10.3, 17.8]** | 17.3% [13.1, 22.5] |

- Pooled over 53.4M rows, only 2.5% are populated; on percent/algorithm rows it is 4.4%.
- The dominant failure is a count of "0" with the medians left blank, seen in 160 of the 217 files that have the fields.
- **Kill check:** even the most generous interval tops out at 22.5%, below the 25% bar. A "posted vs paid" headline cannot rest on population-scale data.

## Ceiling-quantile angle: survives
- Per file, the mean share of cells in each count bin is:
  - 75% masked ("1 through 10")
  - 10% from 11 to 30
  - 9% from 31 to 150
  - 5% over 150
- Dispersion s = log(P90/P10)/2.563 has a median of 0.11 and a p75 of 0.76. 43% of cells exceed 0.3.
- Cells with n > 150 and s < 0.3, where the bias is negligible:
  - 10.1% pooled, but **1.6% excluding New Orleans East**, which contributes 117k of the 135k such cells
  - per-file median 0.4%
  - only 2 of 167 files have 25% or more of their cells there
- For masked cells with n ≤ 10, the published P90 is the sample maximum. That is where the rule's bias is largest (see `methods/ceiling_quantile.md`).

## Posted vs paid (unit-matched)
- **Raw:** the negotiated rate is outside the P10 to P90 band in 63% of cells. This figure is inflated.
- **Per-line vs per-claim is mostly ruled out:** only 2.4% of ratios fall near an integer of 2 or more. Per diem is the exception, at 25%.
- **What does inflate it:**
  - degenerate bands where P10 = P90 (33% of cells)
  - allowed amounts reported per billing code while negotiated rates are per chargemaster item (29 of 167 files; Texas Health's C1713 implants are the clearest case)
- **Outside the band in unit-matched cells** (non-degenerate band, 5% tolerance, hospital-clustered bootstrap CI):
  - DRG/case rate: **30.8% [21.1, 39.6]**, 49 hospitals, with a median allowed/negotiated ratio of 0.99
  - CPT/HCPCS fee schedule: 47.5% [40.4, 56.8], only 14 hospitals
  - everything else: 50.5%

## Defects by system
- **Index blocked even to a browser User-Agent:** AdventHealth ×3, Tenet ×4, City of Hope, Integris, Yale New Haven, MyMichigan, Valley Health/Centra.
- **Price file blocked:** Northside ×3, Avera ×3.
- **Plain client refused (406), browser served:** Ascension ×5.
- **Dignity Health:** `cms-hpt.txt` returns 404; its files are reachable only through CommonSpirit's index.
- **Fields missing entirely:** SGHS, Christus.
- **Other counts:**
  - 27 files encode allowed amounts with count "0", which the spec forbids
  - 25 are served as zips
  - 18 are dated before 2026

## Scorecard (`src/scorecard.py` → `scorecard.csv`, `scorecard_summary.json`)
- Each check is pass, fail, or blank. Blank means not assessable: an upstream step failed, or the failure may be ours (404 on a guessed domain, a timeout, a fuzzy-match miss).
- **Clean on every required check: 61.7% [56.3, 66.8]** of 300 hospitals. Virginia census: 71/91 (78%).
- Populated (fields filled on more than 10% of rows) is descriptive, not required, because CMS's FAQ requires a count of 0 with blank percentiles when a hospital has no claims: 19.8% [15.3, 25.1] of parseable files.
- An earlier version counted populated as required, which gave clean = 10.7% [7.7, 14.5]. It was dropped after reading the FAQ.
- Advisory, so excluded from "clean":
  - bot barrier: 18% [14, 23] of listed files
  - .zip format: CMS's FAQ allows compressed files
- Published values are verified by a second fetch (`src/retest.py`): a failure is shown only if it repeats. All 2,703 national check results agreed across fetches 8 hours apart.
- Page: `site/index.html` + `site/data.json` (from `uv run python src/site.py`).

## Limits
- Files are read from the start only, up to 300 MB each, so the cell-level figures don't cover whole files.
- Domain resolution involved hand judgment.
- Three files dominate the pooled cell counts, so the per-file statistics are the ones to cite.

## Next
1. Restrict posted-vs-paid to DRG case rates and test the mid-lookback renegotiation explanation.
2. Re-fetch weeks later to test whether files are stable over time.
