"""Residual and stationarity diagnostics, standard library only.

Durbin-Watson on regression residuals and a constant-only Augmented Dickey-Fuller test.
"""

from typing import List, Optional, Sequence

from ols import ols

# MacKinnon (2010, Queen's Univ. WP 1227) response surface for the constant-only ADF test:
# CV(n) = t0 + t1/n + t2/n^2 + t3/n^3, n = observations in the test regression.
# Coefficients as in statsmodels tsa/adfvalues.py (tau_c_2010, N=1); t0 is the asymptotic value.
ADF_SURFACE = {
    "1%": (-3.43035, -6.5393, -16.786, -79.433),
    "5%": (-2.86154, -2.8903, -4.234, -40.040),
    "10%": (-2.56677, -1.5384, -2.809, 0.0),
}


def adf_critical(n: int) -> dict:
    """Finite-sample critical values for a constant-only ADF regression with n observations."""
    return {lvl: sum(c / n ** k for k, c in enumerate(th)) for lvl, th in ADF_SURFACE.items()}


def durbin_watson(resid: Sequence[float], index: Optional[Sequence[int]] = None) -> float:
    """About 2 means no first-order autocorrelation; well below 2 means positive autocorrelation.

    `index` gives each residual's position in time. Only pairs exactly one period apart are differenced,
    so gaps are not bridged. If omitted, residuals are treated as consecutive.
    """
    den = sum(e * e for e in resid)
    if den == 0:
        raise ValueError("residuals are all zero")
    if index is None:
        index = range(len(resid))
    pairs = [t for t in range(1, len(resid)) if index[t] - index[t - 1] == 1]
    if not pairs:
        raise ValueError("no consecutive residuals")
    return sum((resid[t] - resid[t - 1]) ** 2 for t in pairs) / den


def adf(series: Sequence[float], lags: int = 4) -> dict:
    """ADF regression: dy_t = a + g*y_(t-1) + sum_i d_i*dy_(t-i) + e_t, i = 1..lags.

    The statistic is g / classical SE. Reject a unit root when it is below a critical value.
    Critical values are MacKinnon finite-sample values for the regression's n.
    shortcut: fixed lag length, no AIC selection; upgrade if the lag choice drives the result.
    """
    dy = [series[t] - series[t - 1] for t in range(1, len(series))]
    X, y = [], []
    for t in range(lags, len(dy)):  # dy[t] is the change into series[t + 1]
        X.append([1.0, series[t]] + [dy[t - i] for i in range(1, lags + 1)])
        y.append(dy[t])
    res = ols(X, y, nw_lags=0)
    stat = res["coef"][1] / res["se_classical"][1]
    crit = adf_critical(res["n"])
    reject = {lvl: stat < c for lvl, c in crit.items()}
    return {"stat": stat, "lags": lags, "n": res["n"], "critical": crit, "reject_unit_root": reject}
