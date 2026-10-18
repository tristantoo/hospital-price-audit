"""Figure 1: rule-attributable relative bias E[CMS7 - T7]/Q(p), exact (Beta integral), n = 2..300.
uv run python paper/figures.py  -> paper/fig_bias.pdf"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "methods"))
import sim  # noqa: E402

ns = np.arange(2, 301)
_, rb = sim.exact_bias(ns)
fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
for ax, P in zip(axes, (50, 90)):
    for d, style in (("lognormal s=0.8", "-"), ("gamma k=2", "--"), ("lognormal s=0.3", ":")):
        ax.plot(ns, 100 * (rb[d, P, "CMS"] - rb[d, P, "T7"]), style, lw=0.9, color="black", label=d.replace("s=", "σ = ").replace("k=", "shape "))
    ax.axvline(10.5, color="0.6", lw=0.6)
    ax.text(12, 44, "n ≤ 10 masked", fontsize=7, color="0.4")
    ax.set_xscale("log")
    ax.set_title("median" if P == 50 else "90th percentile", fontsize=9)
    ax.set_xlabel("number of remittances n", fontsize=8)
    ax.tick_params(labelsize=7)
axes[0].set_ylabel("rule-attributable bias (% of Q(p))", fontsize=8)
axes[1].legend(fontsize=7, frameon=False)
fig.tight_layout()
fig.savefig(ROOT / "paper/fig_bias.pdf")
print("wrote paper/fig_bias.pdf")
