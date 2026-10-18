# Phase 0 findings: Virginia hospital price files (2026-10-17)

Source: `census.csv`, `dispersion.csv`, `dispersion_summary.json`. Each file was sampled at its first ~200k rows, so these numbers come from a bounded sample, not a full read.

## Funnel
- 96 Virginia hospitals are in CMS Hospital General Information. 5 are VA/DoD hospitals, which are federal and exempt, leaving **91 in scope**.
- **82** have a working `cms-hpt.txt` matched to a CCN and a parseable file (74 use template v3.0, 8 use v2.0).
- The 9 failures:
  - Valley Health (4), Centra (3) and Virginia Hospital Center (1) return 403 even to a browser User-Agent.
  - Dominion Hospital returns 404.
- **73** files include the 2026 allowed-amount fields.
- Only **4** populate them on more than 10% of payer rows: UVA Medical Center, UVA Culpeper, Sovah Danville, and Buchanan General.

## Kill check: failed. Go national.
- 4/91 = 4.4% populate the fields, against a 25% threshold.
- CMS requires the fields only where the negotiated rate is a percentage or algorithm. Measured on just those rows, 23/91 = 25.3%, right at the line.
- Most cells report a count of "0", which legally leaves the medians blank.
- **Decision:** Virginia's populated data is too thin. Run the same pipeline on a national sample.

## Ceiling-quantile angle: survives
- There are 221,981 populated cells across 59 files.
- Counts:
  - 69.1% "1 through 10" (masked)
  - 11.5% from 11 to 30
  - 15.5% from 31 to 150
  - 3.8% over 150
- Dispersion s = log(P90/P10)/2.563: median 0.02, p75 0.50, p90 0.87. 33% of cells exceed 0.3.
- Only **0.38%** of cells are both n > 150 and s < 0.3, the region where the bias is negligible. No file has a majority of its cells there.
- Small masked counts dominate. That is where the rule's bias is largest: for n ≤ 10 the published P90 is the sample maximum.

## Posted vs paid: first look only, not representative
- The negotiated rate falls outside the hospital's own P10 to P90 band in 69.6% of cells.
- By count: 81% at n of 1 to 10, 61% at 11 to 30, 48% at 31 to 150, and 47% over 150.
- **Unconfirmed.** Negotiated rates are often per line item, while allowed amounts look claim-level. Units must be reconciled before this means anything.

## Defects (compliance findings in their own right)
- **Bon Secours (11 hospitals):** count of allowed amounts is "0" on every row, with no medians.
- **Carilion Roanoke:** 142k rows have medians that copy the negotiated rate while the count is "0". The spec forbids this, so these rows are excluded from "populated".
- **Stale files:** 8 files are on v2.0 or out of date, including Mary Washington ×2 (dated Dec 2024) and 6 state facilities.
- **Zip files:** 7 price files are served as .zip.
- **User-Agent:** 17 index files refuse Python's default User-Agent but serve a browser one.
- **VCU Health:** 2 index links are Proofpoint `urldefense`-wrapped.

## Next
1. Draw a national frame of about 300 hospitals, stratified by state, system and bed size, then rerun `census.py` and `dispersion.py`.
2. Reconcile units (line-level vs claim-level) before any posted-vs-paid claim.
3. Write the defect list into a compliance scorecard. That part is publishable now.
