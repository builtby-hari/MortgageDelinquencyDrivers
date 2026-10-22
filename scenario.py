"""Scenario projection of the delinquency rate, plus a teaching-only loss illustration.

Paths for unemployment and the 30-year mortgage rate (levels, quarterly) are inputs. The fitted
model turns quarterly changes in those paths into quarterly changes in the delinquency rate, which
are summed onto the last observed rate.

Bands: the sum of h quarterly changes has variance c' V c + h * sigma2, where c is the sum of the
regressor vectors, V is the Newey-West coefficient covariance and sigma2 is the residual variance.
The band is +/- 1.96 standard errors. Shortcut: residual shocks are treated as independent across
quarters, though the residuals are autocorrelated, so the band is likely too narrow at long horizons.

The loss figures are a teaching illustration, not a CECL model.
"""

import csv
import math
import os
from typing import Dict, List, Optional

from analysis import DATA_DIR, MODELS, build_panel, load, quarterly_mean, run_model

HORIZON = 9
Z95 = 1.96
DEFAULT_MODEL = "M4"


def quarter_index(q: str) -> int:
    return int(q[:4]) * 4 + int(q[5]) - 1


def quarter_label(i: int) -> str:
    return f"{i // 4}Q{i % 4 + 1}"


def load_scenarios(path: str, last_quarter: str, horizon: int = HORIZON, rebase: Optional[dict] = None
                   ) -> Dict[str, List[dict]]:
    """Read scenario,quarter,unemployment,mortgage_rate rows. Every scenario must cover exactly the
    `horizon` quarters after `last_quarter`; anything else raises ValueError naming the problem.

    A row for `last_quarter` itself is allowed as an anchor and is ignored by default. With `rebase`
    (the observed {"unemployment", "mortgage_rate"} in `last_quarter`), the anchor row is required and each
    scenario is shifted by observed minus anchor, so it starts from observed levels and keeps its own
    changes. Without rebase the file's levels are used as given."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        need = {"scenario", "quarter", "unemployment", "mortgage_rate"}
        if not need <= set(reader.fieldnames or []):
            raise ValueError(f"{path}: header must contain {', '.join(sorted(need))}")
        found: Dict[str, Dict[str, dict]] = {}
        for n, r in enumerate(reader, start=2):
            name, q = r["scenario"].strip(), r["quarter"].strip()
            try:
                vals = {"unemployment": float(r["unemployment"]), "mortgage_rate": float(r["mortgage_rate"])}
            except (TypeError, ValueError):
                raise ValueError(f"{path} line {n}: unemployment and mortgage_rate must be numbers")
            if q in found.setdefault(name, {}):
                raise ValueError(f"scenario '{name}': quarter {q} appears twice")
            found[name][q] = {"quarter": q, **vals}
    if not found:
        raise ValueError(f"{path}: no scenarios found")
    start = quarter_index(last_quarter) + 1
    want = [quarter_label(start + i) for i in range(horizon)]
    out = {}
    for name, qs in found.items():
        missing = [q for q in want + ([last_quarter] if rebase else []) if q not in qs]
        extra = [q for q in qs if q not in want and q != last_quarter]
        if missing:
            raise ValueError(f"scenario '{name}': missing quarters {', '.join(missing)}")
        if extra:
            raise ValueError(f"scenario '{name}': unexpected quarters {', '.join(extra)} (need {want[0]} to {want[-1]})")
        shift = {k: rebase[k] - qs[last_quarter][k] for k in ("unemployment", "mortgage_rate")} if rebase else {}
        out[name] = [{**qs[q], **{k: qs[q][k] + d for k, d in shift.items()}} for q in want]
    return out


def model_by_id(model_id: str):
    for title, xcols, excl, window in MODELS:
        if title.split()[0] == model_id:
            return title, xcols, excl, window
    raise ValueError(f"unknown model '{model_id}'; choose one of " + ", ".join(m[0].split()[0] for m in MODELS))


def project(res: dict, xcols: List[str], start: dict, path: List[dict], z: float = Z95) -> List[dict]:
    """Project the delinquency level along `path`.

    res: fitted result from run_model (coef, cov, sigma2). start: last observed
    {delinquency, unemployment, mortgage_rate, d_unemp, d_rate}. Returns one dict per quarter with
    d_delinq, level, se, lo, hi.
    """
    k = len(xcols) + 1
    u_prev, r_prev = start["unemployment"], start["mortgage_rate"]
    d_prev = {"d_unemp": start["d_unemp"], "d_rate": start["d_rate"]}
    c = [0.0] * k          # running sum of regressor vectors
    level = start["delinquency"]
    out = []
    for h, step in enumerate(path, start=1):
        d = {"d_unemp": step["unemployment"] - u_prev, "d_rate": step["mortgage_rate"] - r_prev}
        feat = {**d, "d_unemp_lag": d_prev["d_unemp"], "d_rate_lag": d_prev["d_rate"]}
        x = [1.0] + [feat[n] for n in xcols]
        dy = sum(b * v for b, v in zip(res["coef"], x))
        c = [a + v for a, v in zip(c, x)]
        var = sum(c[i] * res["cov"][i][j] * c[j] for i in range(k) for j in range(k)) + h * res["sigma2"]
        level += dy
        se = math.sqrt(var)
        out.append({"quarter": step["quarter"], "unemployment": step["unemployment"],
                    "mortgage_rate": step["mortgage_rate"], "d_delinq": dy, "level": level,
                    "se": se, "lo": level - z * se, "hi": level + z * se})
        u_prev, r_prev, d_prev = step["unemployment"], step["mortgage_rate"], d
    return out


def start_state(rows: List[dict], data_dir: str = DATA_DIR) -> dict:
    q = rows[-1]["quarter"]
    u = quarterly_mean(load(os.path.join(data_dir, "UNRATE.csv")))[q]
    r = quarterly_mean(load(os.path.join(data_dir, "MORTGAGE30US.csv")))[q]
    return {"quarter": q, "delinquency": rows[-1]["delinquency"], "unemployment": u, "mortgage_rate": r,
            "d_unemp": rows[-1]["d_unemp"], "d_rate": rows[-1]["d_rate"]}


def cumulative_loss_rate(levels: List[float], roll_rate: float, lgd: float) -> float:
    """Cumulative loss as a percent of the portfolio: each quarter, roll_rate of the delinquent
    balance (levels are percent of balance) goes to default, and lgd of that is lost.
    Shortcut: no amortization, cures or recoveries timing; the portfolio is held at its starting balance."""
    return sum(max(v, 0.0) * roll_rate * lgd for v in levels)


def loss_table(proj: List[dict], roll_rate: float, lgd: float, portfolio: float) -> dict:
    out = {}
    for key in ("lo", "level", "hi"):
        pct = cumulative_loss_rate([p[key] for p in proj], roll_rate, lgd)
        out[key] = {"pct": pct, "amount": pct / 100.0 * portfolio}
    return out


DEFAULT_SCENARIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios", "illustrative.csv")


def compute(path: str, model_id: str = DEFAULT_MODEL, roll_rate: float = 0.20, lgd: float = 0.25,
            portfolio: float = 10000.0, rebase: bool = False):
    """Return (model title, n, start, {scenario: {"proj": [...], "loss": {...}}})."""
    for name, v in (("roll rate", roll_rate), ("LGD", lgd)):
        if not 0 <= v <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
    if portfolio <= 0:
        raise ValueError("portfolio must be positive")
    rows = build_panel()
    title, xcols, excl, window = model_by_id(model_id)
    res = run_model(rows, xcols, excl, window)
    start = start_state(rows)
    scen = load_scenarios(path, start["quarter"], rebase=start if rebase else None)
    results: Dict[str, dict] = {n: {"proj": project(res, xcols, start, p)} for n, p in scen.items()}
    for r in results.values():
        r["loss"] = loss_table(r["proj"], roll_rate, lgd, portfolio)
    return title, res["n"], start, results


def run(path: str, model_id: str = DEFAULT_MODEL, roll_rate: float = 0.20, lgd: float = 0.25,
        portfolio: float = 10000.0, rebase: bool = False) -> Dict[str, dict]:
    """Print the projection and loss report; return the results."""
    title, n_obs, start, results = compute(path, model_id, roll_rate, lgd, portfolio, rebase)
    print(f"Scenario projection, model {title} (n={n_obs}), starting {start['quarter']} "
          f"delinquency {start['delinquency']:.2f}%")
    if rebase:
        print(f"Paths re-based to the observed {start['quarter']} levels (scenario changes kept).")
    print(f"Bands: 95%, coefficient uncertainty (Newey-West) plus residual noise, {HORIZON} quarters.\n")
    for n, r in results.items():
        print(n)
        print(f"  {'Quarter':<8}{'Unemp':>7}{'Rate':>7}{'Change':>9}{'Level':>8}{'Low':>8}{'High':>8}")
        for p in r["proj"]:
            print(f"  {p['quarter']:<8}{p['unemployment']:>7.2f}{p['mortgage_rate']:>7.2f}"
                  f"{p['d_delinq']:>9.3f}{p['level']:>8.2f}{p['lo']:>8.2f}{p['hi']:>8.2f}")
        print()
    print("Loss illustration (teaching example, not a CECL model)")
    print(f"  Portfolio ${portfolio:,.0f}mm, roll to default {roll_rate:.0%} of delinquent balance per quarter, "
          f"LGD {lgd:.0%}, {HORIZON} quarters")
    print(f"  {'Scenario':<18}{'Loss Rate':>10}{'Low':>8}{'High':>8}{'Loss $mm':>10}")
    for n, r in results.items():
        L = r["loss"]
        print(f"  {n:<18}{L['level']['pct']:>9.2f}%{L['lo']['pct']:>7.2f}%{L['hi']['pct']:>7.2f}%"
              f"{L['level']['amount']:>10.1f}")
    return results
