"""Optional matplotlib versions of the main charts. The core project is standard library only.

This file needs matplotlib (see requirements-extra.txt). Without it, the script prints a message and exits.
Writes PNGs into docs/mpl/.

Usage: python3 plots_mpl.py [--out docs/mpl]
"""

import argparse
import os
from typing import List

from analysis import MODELS, PANDEMIC, build_panel, correlation_matrix, run_model
from charts import PRE_2020, RECESSIONS, THEMES, in_recession

DOCS_MPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "mpl")
NAVY = THEMES["light"]["navy"]
TEAL = THEMES["light"]["teal"]
GREY = "#cbd5e1"
TEXT = "#334155"


def _style(ax, title: str):
    ax.set_title(title, loc="left", fontsize=12, color=TEXT, fontweight="bold")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GREY, linewidth=0.8)
    ax.set_axisbelow(True)


def make_all(out_dir: str) -> List[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(out_dir, exist_ok=True)
    rows = build_panel()
    quarters = [r["quarter"] for r in rows]
    x = list(range(len(rows)))
    paths: List[str] = []

    def save(fig, name):
        path = os.path.join(out_dir, name)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)

    # 1. delinquency level with recessions shaded
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(x, [r["delinquency"] for r in rows], color=NAVY, linewidth=1.8)
    for i, q in enumerate(quarters):
        if in_recession(q):
            ax.axvspan(i - 0.5, i + 0.5, color=GREY, alpha=0.8, linewidth=0)
    ticks = [i for i, q in enumerate(quarters) if q.endswith("Q1") and int(q[:4]) % 5 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([quarters[i][:4] for i in ticks])
    ax.set_ylabel("Delinquency Rate (%)")
    _style(ax, "Single-Family Mortgage Delinquency Rate, Shaded = NBER Recession Quarters")
    save(fig, "delinquency_over_time.png")

    # 2. scatter of changes
    fig, ax = plt.subplots(figsize=(8, 6))
    pandemic = [PANDEMIC[0] <= r["quarter"] <= PANDEMIC[1] for r in rows]
    ax.scatter([r["d_unemp"] for r, p in zip(rows, pandemic) if not p],
               [r["d_delinq"] for r, p in zip(rows, pandemic) if not p], s=18, color=NAVY, alpha=0.75,
               label="Quarters Before 2020 and After")
    ax.scatter([r["d_unemp"] for r, p in zip(rows, pandemic) if p],
               [r["d_delinq"] for r, p in zip(rows, pandemic) if p], s=26, color=TEAL, label="2020 Quarters")
    fit = run_model(rows, ["d_unemp"], window=PRE_2020)
    pre = [r for r in rows if PRE_2020[0] <= r["quarter"] <= PRE_2020[1]]
    lo, hi = min(r["d_unemp"] for r in pre), max(r["d_unemp"] for r in pre)
    a, b = fit["coef"]
    ax.plot([lo, hi], [a + b * lo, a + b * hi], color=TEXT, linewidth=2, label=f"OLS Fit, Pre-2020 (Slope {b:.2f})")
    ax.set_xlabel("Change in Unemployment Rate, q/q (pp)")
    ax.set_ylabel("Change in Delinquency Rate, q/q (pp)")
    ax.legend(frameon=False, fontsize=9)
    _style(ax, "Quarterly Change in Delinquency vs. Unemployment Change")
    save(fig, "delinquency_vs_unemployment.png")

    # 3. coefficients with +/-2 SE
    fig, ax = plt.subplots(figsize=(8, 5))
    coefs = []
    for title, xcols, excl, window in MODELS:
        res = run_model(rows, xcols, excl, window)
        i = res["names"].index("d_unemp")
        coefs.append((res["coef"][i], 2 * res["se"][i]))
    labels = [m[0].split()[0] for m in MODELS]
    for i, (b_, h) in enumerate(coefs):
        ax.errorbar(i, b_, yerr=h, fmt="o", color=NAVY, ecolor=NAVY, capsize=5, markersize=7, linewidth=2)
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Coefficient on Change in Unemployment (pp per pp)")
    _style(ax, "Unemployment-Change Coefficient, Plus or Minus 2 Newey-West SE")
    save(fig, "coefficients.png")

    # 4. actual vs fitted for M2
    fig, ax = plt.subplots(figsize=(9, 4.5))
    res = run_model(rows, ["d_unemp", "d_rate"])
    qs = res["quarters"]
    xi = list(range(len(qs)))
    ax.plot(xi, res["y"], color=NAVY, linewidth=1.2, label="Actual")
    ax.plot(xi, res["fitted"], color=TEAL, linewidth=1.8, label="Fitted")
    ax.axhline(0, color="#64748b", linestyle="--", linewidth=0.8)
    ticks = [i for i, q in enumerate(qs) if q.endswith("Q1") and int(q[:4]) % 5 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([qs[i][:4] for i in ticks])
    ax.set_ylabel("Change in Delinquency, q/q (pp)")
    ax.legend(frameon=False, fontsize=9)
    _style(ax, f"Actual vs. Fitted, Model M2 (R² = {res['r2']:.3f})")
    save(fig, "actual_vs_fitted.png")

    # 5. correlation heatmap
    cols = ["d_delinq", "d_unemp", "d_rate", "d_unemp_lag", "d_rate_lag"]
    labels = ["Δ Delinquency", "Δ Unemployment", "Δ Mortgage Rate", "Δ Unemp, Lag 1", "Δ Rate, Lag 1"]
    M = correlation_matrix(rows, cols)
    fig, ax = plt.subplots(figsize=(7, 6))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("navy_teal", [NAVY, "#f1f5f9", TEAL])
    im = ax.imshow(M, cmap=cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_yticks(range(len(cols)))
    ax.set_yticklabels(labels)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{M[i][j]:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if abs(M[i][j]) > 0.55 else TEXT)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title("Correlation of the Delinquency Change with Its Drivers", loc="left", fontsize=12,
                 color=TEXT, fontweight="bold")
    save(fig, "driver_correlations.png")
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DOCS_MPL)
    args = parser.parse_args()
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("matplotlib is not installed. This script is optional.")
        print("Install it with: pip install -r requirements-extra.txt")
        return
    for path in make_all(args.out):
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
