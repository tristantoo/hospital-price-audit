"""Bias of the CMS "next highest observed value" percentile rule (45 CFR 180.20, CY2026 OPPS).

SKETCH -- not peer reviewed. numpy + scipy only. Run: python sim.py  (~1 min)

Bias is computed EXACTLY (no Monte Carlo noise) from U_(k) ~ Beta(k, n-k+1):
    E X_(k) = E Q(U_(k)) = int_0^1 Q(betaincinv(k, n-k+1, t)) dt   (midpoint rule in t).
RMSE, band content and the corrected estimator use Monte Carlo (R draws per n).
"""
import numpy as np
from scipy import special, stats

PS = (10, 50, 90)                     # percentiles as integers -> exact rank arithmetic
N_REPORT = (10, 30, 100, 500)
M = 1000                              # midpoint nodes for the exact Beta integral
R = 10_000                            # Monte Carlo reps per n
RNG = np.random.default_rng(20261017)


# ---------- estimators (ranks are 1-indexed) ----------
def k_cms(n, P):
    """CMS rule, primary reading: ceil of the type-7 position h=(n-1)p+1 (== numpy method='higher')."""
    return -(-(n - 1) * P // 100) + 1


def k_cms6(n, P):
    """CMS rule, alternate reading: ceil of the type-6 position (n+1)p, clamped to [1, n]."""
    return min(max(-(-(n + 1) * P // 100), 1), n)


def t7(n, P):
    """Hyndman-Fan type 7: (1-g) X_(j) + g X_(j+1)."""
    return (n - 1) * P // 100 + 1, ((n - 1) * P % 100) / 100


def corrected(n, v):
    """Proposed correction from the published summary only: (n, P10, median, P90) -> Q(p) estimates.
    Each reported value is X_(k) with known k. Place it at its Blom normal score
    z_k = Phi^-1((k-3/8)/(n+1/4)) and interpolate/extrapolate log(value) linearly in z to z_p.
    Exact to first order for log-location-scale data; returns the atom when values tie."""
    ks = np.array([k_cms(n, P) for P in PS])
    z = stats.norm.ppf((ks - 0.375) / (n + 0.25))
    y = np.log(v)                                         # v: (..., 3)
    out = []
    for i, P in enumerate(PS):
        zp = stats.norm.ppf(P / 100)
        a, b = (0, 1) if zp <= z[1] else (1, 2)           # segment containing / nearest to z_p
        if z[b] - z[a] < 1e-12:                           # ranks coincide (n <= 3): nothing to fit
            out.append(v[..., i])
            continue
        slope = (y[..., b] - y[..., a]) / (z[b] - z[a])
        out.append(np.exp(y[..., a] + slope * (zp - z[a])))
    return np.stack(out, -1)


# ---------- distributions (all scale-free: relative metrics) ----------
def _scipy(d):
    return dict(ppf=d.ppf, cdf=d.cdf, cdf_left=d.cdf, rvs=lambda size: d.rvs(size=size, random_state=RNG))


# "contract" mixture: fee-schedule rate 1.00, renegotiated rate 1.04 (CMS says pool pre/post renegotiation),
# a reduced rate 0.80, and 20% continuous outlier/carve-out/percent-of-charge tail.
ATOMS, W, WC = np.array([0.80, 1.00, 1.04]), np.array([0.10, 0.50, 0.20]), 0.20
CONT = stats.lognorm(0.5, scale=1.3)


def _mix_cdf(x, left=False):
    x = np.asarray(x, float)
    hit = (x[..., None] > ATOMS) if left else (x[..., None] >= ATOMS)
    return WC * CONT.cdf(x) + (hit * W).sum(-1)


_GRID = np.unique(np.concatenate([np.geomspace(1e-3, 1e3, 1_000_001), ATOMS]))
_FG = _mix_cdf(_GRID)


def _mix_ppf(u):  # inf{x : F(x) >= u}; grid resolution ~1.4e-5 relative
    return _GRID[np.minimum(np.searchsorted(_FG, u, side="left"), _GRID.size - 1)]


def _mix_rvs(size):
    c = RNG.choice(4, size=size, p=[*W, WC])
    return np.where(c == 3, CONT.rvs(size=size, random_state=RNG), ATOMS[np.minimum(c, 2)])


DISTS = {
    "lognormal s=0.3": _scipy(stats.lognorm(0.3)),
    "lognormal s=0.8": _scipy(stats.lognorm(0.8)),
    "gamma k=2": _scipy(stats.gamma(2.0)),
    "contract mixture": dict(ppf=_mix_ppf, cdf=_mix_cdf, cdf_left=lambda x: _mix_cdf(x, left=True), rvs=_mix_rvs),
}


# ---------- exact bias over every n = 1..1000 ----------
def exact_bias(ns):
    T = (np.arange(M) + 0.5) / M
    truth = {d: {P: float(D["ppf"](P / 100)) for P in PS} for d, D in DISTS.items()}
    est = ("CMS", "CMS6", "T7")
    rb = {(d, P, e): np.empty(len(ns)) for d in DISTS for P in PS for e in est}
    for i, n in enumerate(ns):
        plan = {}
        for P in PS:
            j, g = t7(n, P)
            plan[P] = dict(CMS=[(k_cms(n, P), 1.0)], CMS6=[(k_cms6(n, P), 1.0)],
                           T7=[(j, 1 - g), (min(j + 1, n), g)])
        ks = np.unique([k for p in plan.values() for terms in p.values() for k, _ in terms])
        U = special.betaincinv(ks, n - ks + 1, T[:, None])          # (M, K), distribution-free
        for d, D in DISTS.items():
            ex = dict(zip(ks.tolist(), D["ppf"](U).mean(0)))
            for P in PS:
                q = truth[d][P]
                for e in est:
                    rb[d, P, e][i] = (sum(w * ex[k] for k, w in plan[P][e]) - q) / q
    return truth, rb


def last_exceed(ns, x, thr):
    idx = np.flatnonzero(np.abs(x) > thr)
    if idx.size == 0:
        return "never"
    return ">1000" if ns[idx[-1]] == ns[-1] else str(ns[idx[-1]])


# ---------- Monte Carlo: RMSE, band content, corrected estimator ----------
def monte_carlo(d, n, truth):
    D = DISTS[d]
    X = np.sort(D["rvs"]((R, n)), axis=1)
    cms = np.stack([X[:, k_cms(n, P) - 1] for P in PS], -1)
    t7v = np.quantile(X, [P / 100 for P in PS], axis=1, method="linear").T
    cor = corrected(n, cms)
    q = np.array([truth[P] for P in PS])
    rel = lambda e: ((e.mean(0) - q) / q, np.sqrt(((e - q) ** 2).mean(0)) / q)
    content = lambda e: (D["cdf"](e[:, 2]) - D["cdf_left"](e[:, 0])).mean()
    assert np.allclose(cms, np.quantile(X, [P / 100 for P in PS], axis=1, method="higher").T)
    return dict(CMS=rel(cms), T7=rel(t7v), COR=rel(cor), content=(content(cms), content(t7v)))


def main():
    ns = np.arange(1, 1001)
    truth, rb = exact_bias(ns)
    pct = lambda x: f"{100 * x:+.1f}%"

    print("## Exact relative bias E[est]/Q(p) - 1 (Beta integral) and MC RMSE / band content\n")
    print("| dist | n | p | bias CMS | bias T7 | CMS-T7 | CMS-T7 worst n-5..n+4 | RMSE CMS | RMSE T7 | bias corr | RMSE corr | MC bias CMS |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    content_rows = []
    for d in DISTS:
        for n in N_REPORT:
            mc = monte_carlo(d, n, truth[d])
            content_rows.append((d, n, *mc["content"]))
            for i, P in enumerate(PS):
                b = {e: rb[d, P, e][n - 1] for e in ("CMS", "T7")}
                diff = (rb[d, P, "CMS"] - rb[d, P, "T7"])[max(n - 6, 0):n + 4]
                print(f"| {d} | {n} | P{P} | {pct(b['CMS'])} | {pct(b['T7'])} | {pct(b['CMS'] - b['T7'])} | "
                      f"{pct(diff.max())} | {100 * mc['CMS'][1][i]:.1f}% | {100 * mc['T7'][1][i]:.1f}% | "
                      f"{pct(mc['COR'][0][i])} | {100 * mc['COR'][1][i]:.1f}% | {pct(mc['CMS'][0][i])} |")

    print("\n## P10-P90 band content E[F(P90hat) - F(P10hat-)] (nominal 80%)\n")
    print("| dist | n | CMS band | T7 band | CMS closed form (k90-k10)/(n+1) |")
    print("|---|---|---|---|---|")
    for d, n, c_cms, c_t7 in content_rows:
        cf = (k_cms(n, 90) - k_cms(n, 10)) / (n + 1)
        print(f"| {d} | {n} | {100 * c_cms:.1f}% | {100 * c_t7:.1f}% | {100 * cf:.1f}% |")

    print("\n## Largest n (1..1000) at which |relative bias| exceeds 1% / 5% / 10%\n")
    print("| dist | p | CMS vs truth | T7 vs truth | CMS - T7 (rule-attributable) |")
    print("|---|---|---|---|---|")
    for d in DISTS:
        for P in PS:
            cells = [rb[d, P, "CMS"], rb[d, P, "T7"], rb[d, P, "CMS"] - rb[d, P, "T7"]]
            print(f"| {d} | P{P} | " + " | ".join(
                " / ".join(last_exceed(ns, x, t) for t in (0.01, 0.05, 0.10)) for x in cells) + " |")

    print("\n## Readings: share of n in 1..1000 where ceil-type-6 rank != ceil-type-7 rank; max |bias gap|\n")
    for P in PS:
        dis = np.mean([k_cms6(n, P) != k_cms(n, P) for n in ns])
        gap = max(np.abs(rb[d, P, "CMS6"] - rb[d, P, "CMS"])[29:].max() for d in DISTS)
        print(f"- P{P}: ranks differ for {100 * dis:.0f}% of n; max |rel bias gap| for n>=30: {100 * gap:.1f}%")

    print("\n## Distribution-free confidence of statements built only from published order statistics\n")
    print("| n | Q10 <= P10hat | Q90 <= P90hat | Q90 >= medhat | Q50 <= medhat | P10hat <= Q50 <= P90hat |")
    print("|---|---|---|---|---|---|")
    B = stats.binom
    for n in (*range(1, 11), 11, 30, 100, 500):
        k10, k50, k90 = (k_cms(n, P) for P in PS)
        row = [B.cdf(k10 - 1, n, .1), B.cdf(k90 - 1, n, .9), B.sf(k50 - 1, n, .9), B.cdf(k50 - 1, n, .5),
               B.cdf(k90 - 1, n, .5) - B.cdf(k10 - 1, n, .5)]
        print(f"| {n} | " + " | ".join(f"{x:.3f}" for x in row) + " |")


if __name__ == "__main__":
    main()
