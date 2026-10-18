# Hospital price file audit (2026 CMS allowed-amount rule)

Since April 2026, CMS has required hospitals to publish the median, 10th and 90th percentile of the amounts insurers actually paid (45 CFR 180.20). This repo audits whether hospitals do it, and studies the statistics of the percentile rule itself.

**Scorecard and hospital lookup:** https://tristkenn.com/hospital-prices/

## Results (files fetched October 17, 2026)

- A stratified random sample of 300 US hospitals was drawn before any website was looked up, so hospitals with missing or blocked files stay in the denominator. Every non-federal Virginia hospital (91) was also audited.
- **61.7% (95% CI 56.3% to 66.8%)** of US hospitals met every file requirement I could check. Virginia: 71 of 91.
- **19.8% (15.3% to 25.1%)** of readable files report paid amounts on more than a tenth of their rows. Most of the rest enter a claim count of 0, which the rule allows when there are no claims.
- A second fresh fetch 8 hours later reproduced all 2,703 national check results. A failure is published only if it repeats on both fetches.
- Peterson-KFF reported the empty fields first. This audit adds a hospital-level probability sample with non-response kept in the denominator.

Shares are design-weighted, with Wilson intervals on the design-effective sample size.

## The percentile rule

CMS defines each percentile as the "next highest observed value". `paper/` shows that this rule:

- has several readings that disagree on most claim counts;
- reports the maximum as the 90th percentile whenever there are 10 or fewer claims;
- is biased upward by an amount that classical order-statistic results give, with a correction.

The empirical section measures how many real price-file entries are exposed to the bias. The paper is a preprint and has not been peer reviewed. `methods/` holds the simulation behind it.

## Layout

| Path | Contents |
|---|---|
| `src/hpt.py` | Parses `cms-hpt.txt` indexes and price files (CSV, JSON, zip; v2.x and v3.0) |
| `src/national.py` | Stratified sample, domain resolution, design-based estimates |
| `src/census.py` | Fetches and reads each hospital's index and price file |
| `src/scorecard.py` | Grades 11 checks per hospital; pass, fail or not assessable |
| `src/retest.py` | Test-retest agreement (Cohen's kappa) and the verified scorecard |
| `src/site.py` | Builds `site/data.json` for the web page |
| `paper/` | Preprint source, figure and empirical scripts |
| `data/national`, `data/recon` | Sample frame, census results, scorecards (US sample, Virginia) |

## Reproduce

Requires [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run pytest
uv run python src/census.py --frame data/national/domains.csv --out data/national --raw data/raw/national
uv run python src/scorecard.py data/national
uv run python src/retest.py data/national
```

The census downloads up to 300 MB per hospital (about 26 GB in total). Raw files are not committed. Hospital files change over time, so a fresh run will not match these numbers exactly.

## Authorship

Built with AI coding assistance (Claude Code). I set the scope and questions and reviewed the methods, code and results.

Tristan Kennedy, Department of Mathematics and Statistics, Virginia Commonwealth University.
