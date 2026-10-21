"""Do unemployment and mortgage rates explain quarterly changes in mortgage delinquency?

Quarterly panel from FRED:
  delinquency  DRSFRMACBS, quarter-start observations, percent
  unemployment UNRATE, monthly, averaged within each quarter
  mortgage     MORTGAGE30US, weekly, averaged within each quarter

Models regress the quarter-over-quarter change in delinquency (percentage points) on
changes in unemployment and mortgage rates, with Newey-West standard errors.
Associations only. These are not causal estimates.

Usage: python3 analysis.py [--panel panel.csv]
"""

import argparse
import csv
import datetime as dt
import math
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ols import ols

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PANDEMIC = ("2020Q1", "2020Q4")   # forbearance and the spike distort this period


def load(path: str) -> List[Tuple[str, float]]:
    out = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for d, v in reader:
            if v.strip() not in ("", "."):
                out.append((d, float(v)))
    return out


def quarter_key(date: str) -> str:
    d = dt.date.fromisoformat(date)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarterly_mean(series: List[Tuple[str, float]]) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = defaultdict(list)
    for d, v in series:
        buckets[quarter_key(d)].append(v)
    return {q: sum(vs) / len(vs) for q, vs in buckets.items()}


def build_panel() -> List[dict]:
    delinq = {quarter_key(d): v for d, v in load(os.path.join(DATA_DIR, "DRSFRMACBS.csv"))}
    unemp = quarterly_mean(load(os.path.join(DATA_DIR, "UNRATE.csv")))
    rate = quarterly_mean(load(os.path.join(DATA_DIR, "MORTGAGE30US.csv")))

    quarters = sorted(set(delinq) & set(unemp) & set(rate))
    rows = []
    for i in range(1, len(quarters)):
        q, p = quarters[i], quarters[i - 1]
        rows.append({
            "quarter": q,
            "t_index": int(q[:4]) * 4 + int(q[5]),
            "delinquency": delinq[q],
            "d_delinq": delinq[q] - delinq[p],
            "d_unemp": unemp[q] - unemp[p],
            "d_rate": rate[q] - rate[p],
        })
    # lagged regressors need the previous row
    for i, r in enumerate(rows):
        r["d_unemp_lag"] = rows[i - 1]["d_unemp"] if i > 0 else None
        r["d_rate_lag"] = rows[i - 1]["d_rate"] if i > 0 else None
    return rows


def run_model(rows: List[dict], xcols: List[str], exclude_pandemic: bool = False,
              window: Optional[Tuple[str, str]] = None) -> dict:
    usable = [r for r in rows if all(r[c] is not None for c in xcols)]
    if exclude_pandemic:
        usable = [r for r in usable if not (PANDEMIC[0] <= r["quarter"] <= PANDEMIC[1])]
    if window is not None:
        usable = [r for r in usable if window[0] <= r["quarter"] <= window[1]]
    X = [[1.0] + [r[c] for c in xcols] for r in usable]
    y = [r["d_delinq"] for r in usable]
    res = ols(X, y, nw_lags=4, index=[r["t_index"] for r in usable])
    res["names"] = ["const"] + xcols
    res["quarters"] = [r["quarter"] for r in usable]
    res["y"] = y
    res["fitted"] = [yi - ei for yi, ei in zip(y, res["resid"])]
    return res


def pearson(a: List[float], b: List[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb)


def correlation_matrix(rows: List[dict], cols: List[str]) -> List[List[float]]:
    """Pearson correlations among cols, using only rows where every column is present."""
    usable = [r for r in rows if all(r[c] is not None for c in cols)]
    data = {c: [r[c] for r in usable] for c in cols}
    return [[pearson(data[a], data[b]) for b in cols] for a in cols]


# (title, regressors, exclude pandemic, window). The window is inclusive on quarter labels.
MODELS = [
    ("M1  Unemployment change", ["d_unemp"], False, None),
    ("M2  + Mortgage rate change", ["d_unemp", "d_rate"], False, None),
    ("M3  + one-quarter lags", ["d_unemp", "d_unemp_lag", "d_rate", "d_rate_lag"], False, None),
    ("M4  M2 excluding 2020 pandemic", ["d_unemp", "d_rate"], True, None),
    ("M5  M2, pre-2020 sample", ["d_unemp", "d_rate"], False, ("1991Q1", "2019Q4")),
    ("M6  M2, 2021 onward (short sample)", ["d_unemp", "d_rate"], False, ("2021Q1", "2026Q2")),
]


def report(rows: List[dict]) -> None:
    print(f"Panel: {rows[0]['quarter']} to {rows[-1]['quarter']} ({len(rows)} quarters of changes)")
    print("Dependent variable: quarterly change in delinquency rate (pp). Newey-West SEs, 4 lags.\n")
    for title, xcols, excl, window in MODELS:
        res = run_model(rows, xcols, excl, window)
        print(title + f"   n={res['n']}  R²={res['r2']:.3f}")
        print(f"  {'Term':<14}{'Coef':>10}{'SE':>10}{'t':>8}")
        for name, b, s, t in zip(res["names"], res["coef"], res["se"], res["t"]):
            print(f"  {name:<14}{b:>10.3f}{s:>10.3f}{t:>8.2f}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", default="panel.csv")
    args = parser.parse_args()

    rows = build_panel()
    report(rows)

    cols = ["quarter", "delinquency", "d_delinq", "d_unemp", "d_rate", "d_unemp_lag", "d_rate_lag"]
    with open(args.panel, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (round(r[c], 4) if isinstance(r[c], float) else r[c]) for c in cols})
    print(f"Wrote {args.panel}")


if __name__ == "__main__":
    main()
