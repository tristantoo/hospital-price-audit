# The CMS "next highest observed value" percentile rule: bias, readings, correction

> **Status: SKETCH, not peer reviewed.** The derivations are standard order-statistic results that I have not had externally checked. The numbers come from `sim.py` (exact Beta integrals for bias, Monte Carlo for RMSE and band content). The data-generating processes are stylized; no real 835 or MRF data was used.

---

## 1. The rule, quoted from primary sources

**Regulation, 45 CFR § 180.20** (as amended at 90 FR 54087, Nov. 25, 2025; text pulled from eCFR):

> "*Median allowed amount* means the median of the total allowed amounts the hospital has historically received from a third party payer for an item or service for a time period no less than 12 months and no longer than 15 months prior to posting the machine-readable file. Should the calculated median fall between two observed allowed amounts, the median allowed amount is the next highest observed value."

> "*Tenth (10th) percentile allowed amount* means the 10th percentile of the total allowed amounts … Should the calculated percentile fall between two observed allowed amounts, the 10th percentile allowed amount is the next highest observed value."

The definition of the *Ninetieth (90th) percentile allowed amount* uses the same wording.

**Final-rule preamble, 90 FR 53993** (FR Doc. 2025-20907). This is CMS's own gloss, and it matters for §2:

> "We are also finalizing at § 180.20 that should the calculated percentile fall between two observed allowed amounts (in other words, where the total count, n, is an even number), the allowed amount will be the next highest observed value."

**The objection and CMS's response, 90 FR 53990:**

> Commenters: "this deviation from the standard way of calculating a percentile when it falls between two observed values would require hospitals to implement custom formulas for these calculations rather than the 'out-of-the-box' formulas"

> CMS: "We appreciate commenters' concerns that the proposed methodology … is not standard … However, … we believe the need to identify the actual dollar value a hospital has received is consistent with our statutory authority…"

The Cleverley + Associates post of Dec 1, 2025 restates the rule ("hospitals must use the next highest value … so that the reported value in the MRF represents an observed claim amount"). The page I fetched does not itself contain the "not standard" objection, so I cite the Federal Register comment summary for that objection.

**CMS data dictionary v3.0** (`documentation/CSV/README.md`, "Additional Notes for Allowed Amounts") repeats the preamble's even-n gloss word for word. It adds:

> "Hospitals must use EDI 835 ERA transaction data or an alternative equivalent source of remittance data … Hospitals should exclude $0 dollar remittances when calculating and encoding the allowed amounts. If the count of allowed amounts is zero, do not encode these data elements."

**Small-count rule.** The data dictionary's `count` field says:

> "Allowed values are "0", "1 through 10", and whole numbers 11 and greater … If the number of remittances is greater than 0 but less than 11, encode "1 through 10"."

The preamble (90 FR 53998) gives the reason as "align with the CMS Cell Suppression Policy". Only the *count* is masked. The three percentiles are still published for cells with 1 to 10 remittances. There is no minimum n for publishing a percentile: a commenter asked for P10 and P90 to be required only when n > 10, and CMS did not adopt that.

**Ties and duplicates.** No source addresses them. "Count of remittances" implies each remittance is one observation, so duplicate amounts are kept. When the two bracketing values are equal, the rule changes nothing.

**Lookback and webinar.** The CMS webinar of Feb 11, 2026 (slide 15) reproduces the § 180.20 definitions. Slide 23 says: "should the calculated percentile fall between two observed allowed amounts, use the next highest observed value". Slide 22 says the lookback pools data from before and after any contract renegotiation.

## 2. Formalization

Let X_(1) ≤ … ≤ X_(n) be the n allowed amounts, sorted. The rule never says how the "calculated percentile" is computed. Its only operational gloss ("falls between" ⇔ n even) pins down the median and nothing else. Any position rule h(n,p) with h(n,½) = (n+1)/2 satisfies the gloss, which covers Hyndman–Fan types 5–9. "Next highest observed value" then means **k = ⌈h⌉**.

**Primary reading (CMS7).** Take the out-of-the-box default, type 7 (R `quantile`, NumPy, Excel `PERCENTILE.INC`), whose position is h = (n−1)p + 1. Then

  **CMS_p = X_(k), k = ⌈(n−1)p⌉ + 1**  (identical to NumPy `method="higher"`; checked in `test_sim.py`).

- Median: k = ⌊n/2⌋ + 1, the **upper** median.
- P10: k = ⌈(n−1)/10⌉ + 1.
- P90: k = ⌈9(n−1)/10⌉ + 1.
- For every masked cell (n ≤ 10), the published **P90 is the sample maximum**. For 2 ≤ n ≤ 11 the published P10 is X_(2).

**Hyndman–Fan mapping.** CMS7 is **not** any of the nine Hyndman–Fan types.

- It is **not type 1** (inverse ECDF, k = ⌈np⌉). For even n, type 1 gives the *lower* median X_(n/2), which is exactly what the CMS gloss rules out.
- Exactly, CMS7 = F̂_n⁻¹(p + (1−p)/n). That is a type-1 quantile taken at an inflated level, since ⌈n·p + 1 − p⌉ = ⌈(n−1)p⌉ + 1.
- The CMS7 rank is never below the type-1 rank and exceeds it by at most one. The two coincide for a fraction p of the n values, so they differ for 90% of n at P10, 50% at the median and 10% at P90.

**Alternate readings.**

- Ceiling of the type-6 position, CMS6: k = ⌈(n+1)p⌉ clamped to [1,n]. This is SPSS and Excel `PERCENTILE.EXC`.
- Upper inverse ECDF: ⌊np⌋ + 1 (SAS-style).

Both agree with CMS7 at the median. At P10 and P90 the readings disagree by **one rank for ~80% of n**, and the resulting bias gap reaches **17.5% even for n ≥ 30** (σ = 0.8 lognormal). The regulation is therefore under-specified at the tails, and two compliant hospitals can publish different order statistics from identical data.

## 3. Bias theory

**Setup.** Let U_(k) be uniform order statistics, so U_(k) ~ Beta(k, n−k+1), X_(k) = Q(U_(k)) and E U_(k) = k/(n+1). Write the type-7 position h = (n−1)p + 1, with j = ⌊h⌋ and g = h − j. The rounding gap is **δ_n = ⌈h⌉ − h ∈ [0,1)**:

| p | δ_n |
|---|---|
| median | ½ for even n, 0 for odd n |
| P10 | ((−(n−1)) mod 10)/10 |
| P90 | ((n−1) mod 10)/10 |

**Result 1 (exact, pathwise).** T7 = X_(j) + g(X_(j+1) − X_(j)), and CMS7 = X_(⌈h⌉). Therefore

  CMS7 − T7 = δ_n · S_j,  where S_j = X_(j+1) − X_(j) ≥ 0.

So **CMS7 ≥ T7 on every sample**: the rule only ever moves the estimate up. The rule-attributable bias is δ_n·E S_j.

**Result 2 (exact expected spacing).** Derivation, step by step:

1. Assume Q is absolutely continuous on (0,1). Then S_j = Q(U_(j+1)) − Q(U_(j)) = ∫₀¹ Q′(u) 1{U_(j) < u ≤ U_(j+1)} du.
2. Take expectations and use Tonelli: E S_j = ∫₀¹ Q′(u) P(U_(j) < u ≤ U_(j+1)) du.
3. The event in step 2 means exactly j of the n uniforms fall below u. So P(·) = C(n,j) u^j (1−u)^{n−j}.
4. Rewrite that probability as C(n,j) u^j (1−u)^{n−j} = (1/(n+1)) · Beta(j+1, n−j+1) density at u.
5. Therefore **E S_j = E[Q′(V)] / (n+1), with V ~ Beta(j+1, n−j+1).**
6. Hence **E[CMS7 − T7] = δ_n · E[Q′(V)] / (n+1) exactly**. Because V → p at rate n^{-1/2}, and assuming Q′ is smooth near p:

  **E[CMS7 − T7] = δ_n / ((n+1) f(Q(p))) + O(n⁻²).**

**Concrete lognormal case.** For lognormal(0,σ), Q(p)·f(Q(p)) = φ(z_p)/σ. The relative rule bias is therefore ≈ **δ_n σ / ((n+1) φ(z_p))**.

| Quantile | Coefficient σ/φ(z_p) at σ = 0.8 | Approximation | Exact (sim) |
|---|---|---|---|
| P90 (φ = 0.1755) | 4.56 | n=30, δ=0.9: 13.2%; n=100: 4.06% | 14.3%; 4.2% |
| Median (φ = 0.399) | 2.01 | n=30, δ=½: 3.2% | 3.4% |

**Bias against the truth.** This follows from the standard expansion E X_(k) = Q(k/(n+1)) + ½Q″·Var U_(k) + O(n⁻²), as in David & Nagaraja, *Order Statistics*, §4.6. Since k/(n+1) − p = (1 − 2p + δ_n)/(n+1):

  Bias(CMS7) = [(1 − 2p + δ_n) Q′(p) + ½ p(1−p) Q″(p)] / n + O(n⁻²)

  Bias(T7)  = [(1 − 2p) Q′(p) + ½ p(1−p) Q″(p)] / n + O(n⁻²)

What this means for each quantile:

- **P10:** type 7 is already biased upward, by +0.8·Q′/n. The rule adds δ_n·Q′/n on top.
- **P90:** the rule's term (+δ_n) and type 7's downward first-order term (−0.8) partly cancel. But the convex upper tail (Q″ > 0) pushes the total upward. Since δ_n can reach 0.9, this is where the rule bites hardest.
- **Median:** the bias is ½·Q′/n for even n.

**Band content.** For continuous F, E[F(X_(k90)) − F(X_(k10))] = (k90 − k10)/(n+1) exactly. Under CMS7 this is 72.7% at n=10, 77.4% at n=30 and 79.2% at n=100, against a nominal 80%. The CMS band is still *closer* to 80% than the type-7 band (66%, 75%, 78.5%).

## 4. Simulation (`sim.py`, ~25 s)

**Protocol.**

- Bias: E X_(k) = ∫₀¹ Q(I⁻¹(t; k, n−k+1)) dt, midpoint rule with 1,000 nodes, for **every n = 1…1000**. This is exact up to quadrature, with no Monte Carlo error.
- RMSE, band content and the corrected estimator: Monte Carlo with R = 10,000 per n. The Monte Carlo bias reproduces the exact bias to within about 2 MC SE (last column of the sim output).
- Distributions (relative metrics, so scale-free): lognormal σ = 0.3 and σ = 0.8; gamma with shape 2; and a **contract mixture**.
- The contract mixture has atoms at 0.80 (10%), 1.00 (50%, the fee-schedule rate) and 1.04 (20%, the rate after renegotiation; CMS requires pooling both). The remaining 20% is a continuous lognormal(log 1.3, 0.5) outlier/carve-out tail. All three true quantiles sit on atoms.
- No significance test is needed. The bias is computed rather than estimated, and CMS7 ≥ T7 holds on every sample.

**Phase warning.** The reporting n values (10, 30, 100, 500) all have n−1 ≡ 9 (mod 10). That is the **worst** rounding phase for P90 (δ = 0.9) and the **best** for P10 (δ = 0.1). The "worst-phase" column takes the maximum over n−5…n+4.

### Relative bias (exact)

Each cell lists n = 10 / 30 / 100 / 500.

| dist | p | CMS7 vs truth | T7 vs truth | **CMS7 − T7** | CMS7 − T7, worst phase |
|---|---|---|---|---|---|
| LN σ=0.3 | P10 | 9.8 / 3.5 / 1.1 / 0.2 | 8.2 / 3.0 / 0.9 / 0.2 | 1.6 / 0.6 / 0.2 / 0.0 | 13.6 / 4.2 / 1.4 / 0.3 |
| | P50 | 4.5 / 1.5 / 0.4 / 0.1 | 0.7 / 0.2 / 0.1 / 0.0 | 3.7 / 1.2 / 0.4 / 0.1 | 6.1 / 1.4 / 0.4 / 0.1 |
| | P90 | 9.7 / 3.0 / 0.9 / 0.2 | −5.5 / −2.1 / −0.7 / −0.1 | 15.2 / 5.1 / 1.5 / 0.3 | same |
| LN σ=0.8 | P10 | 33.8 / 11.6 / 3.5 / 0.7 | 29.4 / 10.1 / 3.1 / 0.6 | 4.3 / 1.5 / 0.5 / 0.1 | 48.6 / 12.0 / 3.9 / 0.8 |
| | P50 | 15.8 / 5.1 / 1.5 / 0.3 | 5.5 / 1.7 / 0.5 / 0.1 | 10.3 / 3.4 / 1.0 / 0.2 | 17.6 / 3.9 / 1.0 / 0.2 |
| | P90 | 38.2 / 10.6 / 3.0 / 0.6 | −9.0 / −3.7 / −1.2 / −0.2 | **47.2 / 14.3 / 4.2 / 0.8** | same |
| Gamma k=2 | P10 | 42.8 / 15.0 / 4.6 / 0.9 | 37.3 / 13.1 / 4.0 / 0.8 | 5.5 / 1.9 / 0.6 / 0.1 | 57.9 / 15.6 / 5.2 / 1.1 |
| | P50 | 12.6 / 4.2 / 1.3 / 0.3 | 3.2 / 1.0 / 0.3 / 0.1 | 9.4 / 3.2 / 0.9 / 0.2 | 15.5 / 3.6 / 1.0 / 0.2 |
| | P90 | 18.8 / 5.8 / 1.7 / 0.3 | −9.8 / −3.8 / −1.2 / −0.2 | 28.7 / 9.6 / 2.9 / 0.6 | same |
| Mixture | P10 | 13.4 / 8.5 / 3.1 / 0.1 | 11.9 / 7.9 / 3.0 / 0.1 | 1.5 / 0.5 / 0.1 / 0.0 | 7.9 / 4.5 / 1.5 / 0.0 |
| | P50 | 1.0 / 0.2 / 0.0 / 0.0 | 0.6 / 0.1 / 0.0 / 0.0 | 0.4 / 0.1 / 0.0 / 0.0 | 1.3 / 0.1 / 0.0 / 0.0 |
| | P90 | 39.9 / 13.2 / 3.6 / 0.5 | −0.2 / −0.9 / −1.3 / −0.6 | 40.1 / 14.1 / 4.9 / 1.1 | same |

### RMSE

Values in %, CMS7 vs T7.

| dist | quantile | n=10 | n=30 | n=100 |
|---|---|---|---|---|
| LN σ=0.8 | P90 | 86 vs 37 | 31 vs 23 | 15.0 vs 13.6 |
| Mixture | P90 | 78 vs 31 | 34 vs 23 | 17.8 vs 15.9 |

At P10 and the median, the two estimators' RMSE differs by up to about 8 points at n = 10 and by at most 2 points at n ≥ 30. Sampling error dominates per-cell error once n ≥ 30. The bias is one-signed, however, so it does not average out across cells.

### Largest n at which |rule-attributable bias| (CMS7 − T7) exceeds 1% / 5% / 10%

| dist | P10 | median | P90 |
|---|---|---|---|
| LN σ=0.3 | 142 / 23 / 6 | 36 / 6 / 2 | 150 / 30 / 10 |
| LN σ=0.8 | 402 / 72 / 33 | 100 / 20 / 10 | 410 / 80 / 40 |
| Gamma k=2 | 532 / 102 / 43 | 94 / 18 / 8 | 290 / 50 / 20 |
| Mixture | 132 / 22 / 3 | 6 / 2 / 2 | 560 / 90 / 40 |

The same thresholds measured for CMS7 against the truth are in the sim output. For example, at P90 with σ = 0.8 they are 290 / 60 / 30.

**Ties.** Atoms neutralize the rule wherever a quantile sits well inside an atom: the mixture median shows 0.0% from n ≥ 30. The rule still bites when the quantile is near an atom's edge, as with the mixture P90, where F(1.04) = 0.926 and the next order statistic often lands in the continuous tail. The hypothesis "ties make it irrelevant" therefore holds for the median and fails at P90.

## 5. Correction from the published summary (P10, median, P90, n) only

**What can be recovered.**

- When n ≥ 11, n is known, so the published values are exactly X_(k10), X_(k50) and X_(k90), with k from §2. This assumes the CMS7 reading, which is itself unverifiable (see below).

**Corrected point estimator** (in `sim.py: corrected`):

1. Place each published value at its Blom normal score z_k = Φ⁻¹((k − 3/8)/(n + 1/4)).
2. Linearly interpolate or extrapolate log(value) in z to z_p.
3. When published values tie, return the atom unchanged.

This is exact to first order for log-location-scale data. It removes most of the bias in the continuous cases, for example LN σ = 0.8 at n = 30: P90 bias drops from +10.6% to +3.0%, and RMSE from 30.9% to 26.1%. It also matches or beats T7's RMSE at P10 and the median. It helps less on the mixture (P90 at n = 30 goes from +13.2% to +10.1%), because the atom-plus-tail shape is not log-linear.

**Distribution-free bounds.** These hold for any F, as "≥" when F has atoms. With B ~ Bin(n,p):

- P(Q(p) ≤ X_(k)) ≥ P(B ≤ k−1)
- P(X_(i) ≤ Q(p)) ≥ P(B ≥ i)

Applied to the three published order statistics (from the sim output):

| n | Q10 ≤ P̂10 | Q90 ≤ P̂90 | Q90 ≥ med̂ | Q50 ∈ [P̂10, P̂90] |
|---|---|---|---|---|
| 11 | 0.70 | 0.30 | 1.00 | 0.99 |
| 30 | 0.65 | 0.59 | 1.00 | 1.00 |
| 100 | 0.58 | 0.55 | 1.00 | 1.00 |
| 500 | 0.54 | 0.52 | 1.00 | 1.00 |

For masked cells (1–10), take the minimum over n = 1…10. For example, Q90 ≤ P̂90 holds with confidence only 0.10–0.65.

**What cannot be recovered.**

1. **Two-sided distribution-free CIs for P10 or P90 at conventional levels.** Each tail has one order statistic on one side. A 95% interval needs ranks k ± 1.96√(np(1−p)), which are not published. The median gets only a very conservative bracket, [P̂10, P̂90].
2. **Which reading the hospital used** (CMS7, CMS6 or ⌊np⌋+1). This leaves a one-rank ambiguity at the tails that is as large as the rule's own bias.
3. **n within 1–10.**
4. **Tail shape beyond the published points, and whether atoms exist,** except when published values coincide.
5. **The $0 exclusion.** Dropping denials truncates the distribution. This is a separate and probably larger distortion that no summary-level correction can undo.
6. **Non-stationarity.** Pooling pre- and post-renegotiation rates makes "the" quantile a quantile of a mixture over time.

**Hierarchical shrinkage for low-n cells** (sketch, not fitted). A cell c = (hospital h, payer-plan j, code s) reports y_c = log(P̂10, med̂, P̂90) with ranks k(n_c).

- **Within cell:** log X ~ π_c δ_{log r_c} + (1 − π_c) N(μ_c, σ_c²). The atom r_c is the contract rate; set π_c = 0 for pure percent-of-charge cells.
- **Exact summary likelihood.** For continuous F_c with ranks i < j < l:
  L_c = n!/[(i−1)!(j−i−1)!(l−j−1)!(n−l)!] · F^{i−1} (F_j − F_i)^{j−i−1} (F_l − F_j)^{l−j−1} (1 − F_l)^{n−l} · f_i f_j f_l
  For masked cells, L_c = Σ_{n=1}^{10} L_c(n) π(n | volume model). When the published values tie, use the discrete version, which is the atom's multinomial probability.
- **Pooling:** μ_c = α_s + β_h + γ_j + u_c with u_c ~ N(0, τ_s²); log σ_c = λ_s + v_c with v_c ~ N(0, ω²); β_h ~ N(x_hᵀθ, τ_h²), where x_h holds hospital covariates (system, CBSA, wage index).
- **Target:** Q_c(p), the posterior of exp(μ_c + σ_c z_p) or the corresponding mixture quantile. Low-n cells have flat order-statistic likelihoods, so they shrink toward α_s + β_h + γ_j.
- **Cheap version:** take the corrected log-quantile q̂_c with sampling variance v_c ≈ p(1−p)σ̂_c² / (n_c φ(z_p)²), and shrink normal–normal: q̃_c = w_c q̂_c + (1 − w_c) m_s, with w_c = τ²/(τ² + v_c).

## 6. Kill check: is the bias material at realistic n (10–500)?

**Verdict: material, so a methods note is worth writing.** Scope it narrowly.

**What the rule does:**

- The rule-attributable upward bias at **P90** is **≥5% up to n ≈ 30–90 and ≥1% up to n ≈ 150–560** for the dispersed shapes (LN σ = 0.8, gamma, the mixture). At n = 30 and σ = 0.8 it is +14% at P90 and raises P90 RMSE by about 30%.
- At the **median** it is ≥1% up to n ≈ 36–100 (even n).
- In **every masked cell (n ≤ 10), the published P90 is the sample maximum.**
- The rule is **under-specified** at P10 and P90. Readings disagree by one rank for about 80% of n, with gaps up to 17% even at n ≥ 30, so cross-hospital comparability (CMS's stated goal) is not guaranteed by the rule itself.

**Where it is negligible:**

- Tight cells (σ ≤ 0.3) with n > 150.
- Median cells sitting inside a fee-schedule atom.
- Any single cell where n ≥ 30. There sampling noise (RMSE 7–30%) dwarfs the bias.

The note's argument therefore rests on aggregation and comparability, not on per-cell error.

**What would falsify "material".** Real MRFs might show mostly tight within-cell dispersion with large n:

- Estimate σ̂ ≈ log(P̂90/P̂10)/2.563 together with the count distribution.
- If most cells have σ̂ < 0.3 and n > 150, the effect is under 1–2% and the angle should be dropped.

**This check is the first thing to run on real data, before writing the note.** The allowed-amount fields are only required for percentage and algorithm cells. Those are the charge-driven, dispersed cells, which argues the effect will survive, but that is not yet measured.

## Sources

- 45 CFR § 180.20 (eCFR, accessed 2026-10-17): https://www.ecfr.gov/current/title-45/part-180/section-180.20
- CY 2026 OPPS/ASC final rule, 90 FR 53448 (FR Doc. 2025-20907, Nov. 25, 2025). Rule discussion at 90 FR 53988–53999; regulatory text at 90 FR 54087. https://www.federalregister.gov/d/2025-20907
- CMS Hospital Price Transparency data dictionary v3.0, CSV README: https://github.com/CMSgov/hospital-price-transparency/blob/master/documentation/CSV/README.md
- CMS webinar "Reviewing the CY 2026 OPPS/ASC Final Rule" (Feb 11, 2026), slides 15, 16, 22 and 23: https://www.cms.gov/files/document/webinar-hospital-price-transparency-cy2026-opps-asc-final-rule-slides.pdf
- Cleverley + Associates, "CY26 OPPS Final Rule: Hospital Price Transparency Change" (Dec 1, 2025): https://www.cleverleyassociates.com/blog/cy26-opps-final-rule-hospital-price-transparency-change/
- Hyndman, R. J. & Fan, Y. (1996). Sample quantiles in statistical packages. *The American Statistician* 50(4), 361–365.
- David, H. A. & Nagaraja, H. N. (2003). *Order Statistics*, 3rd ed. Wiley.
- ResDAC, CMS Cell Size Suppression Policy (cited at 90 FR 53998 fn. 468).
