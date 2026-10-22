"""Small OLS with Newey-West (HAC) standard errors, using only the standard library.

Matrices are lists of lists. X includes the constant column if you want an intercept.
"""

import math
from typing import List, Optional, Sequence

Matrix = List[List[float]]


def transpose(A: Matrix) -> Matrix:
    return [list(col) for col in zip(*A)]


def matmul(A: Matrix, B: Matrix) -> Matrix:
    Bt = transpose(B)
    return [[sum(a * b for a, b in zip(row, col)) for col in Bt] for row in A]


def inverse(A: Matrix) -> Matrix:
    """Gauss-Jordan inverse with partial pivoting."""
    n = len(A)
    tol = 1e-12 * max(abs(v) for row in A for v in row)  # relative to matrix scale
    M = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < tol:
            raise ValueError("matrix is singular")
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
    return [row[n:] for row in M]


def default_nw_lags(n: int) -> int:
    """Newey-West (1994) rule of thumb: floor(4 * (n / 100) ** (2 / 9)). Gives 4 for n = 140."""
    return int(4 * (n / 100.0) ** (2.0 / 9.0))


def ols(X: Matrix, y: Sequence[float], nw_lags: int = 4, index: Optional[Sequence[int]] = None):
    """Return dict with coef, se (Newey-West), cov (Newey-West covariance matrix), sigma2 (residual variance),
    se_classical (homoskedastic), t, r2, n, resid.

    `index` gives each row's position in time (for example, a quarter number). Newey-West lag products
    then pair only rows exactly `lag` periods apart, so gaps from dropped periods are not bridged.
    If omitted, rows are treated as consecutive.
    """
    if not X:
        raise ValueError("X is empty")
    n, k = len(X), len(X[0])
    if len(y) != n or any(len(row) != k for row in X):
        raise ValueError("X rows must all have the same length and match len(y)")
    if n <= k:
        raise ValueError(f"need more observations than regressors (n={n}, k={k})")
    if nw_lags < 0:
        raise ValueError("nw_lags must be >= 0")
    if index is None:
        index = list(range(n))
    if len(index) != n or len(set(index)) != n:
        raise ValueError("index must have one unique value per row")
    position = {idx: t for t, idx in enumerate(index)}
    Xt = transpose(X)
    XtX_inv = inverse(matmul(Xt, X))
    beta = [sum(XtX_inv[i][j] * sum(Xt[j][t] * y[t] for t in range(n)) for j in range(k)) for i in range(k)]
    resid = [y[t] - sum(X[t][j] * beta[j] for j in range(k)) for t in range(n)]

    # Newey-West: S = sum_t x_t e_t e_t x_t' + sum_l w_l sum_t (x_t e_t x_{t-l} e_{t-l}' + transpose)
    def score(t):
        return [X[t][j] * resid[t] for j in range(k)]

    S = [[0.0] * k for _ in range(k)]
    for t in range(n):
        s = score(t)
        for i in range(k):
            for j in range(k):
                S[i][j] += s[i] * s[j]
    for lag in range(1, nw_lags + 1):
        w = 1.0 - lag / (nw_lags + 1.0)
        for t in range(n):
            s_pos = position.get(index[t] - lag)
            if s_pos is None:
                continue
            a, b = score(t), score(s_pos)
            for i in range(k):
                for j in range(k):
                    d = w * (a[i] * b[j] + b[i] * a[j])
                    S[i][j] += d
    V = matmul(matmul(XtX_inv, S), XtX_inv)
    se = [math.sqrt(max(V[i][i], 0.0)) for i in range(k)]

    ybar = sum(y) / n
    ss_tot = sum((v - ybar) ** 2 for v in y)
    ss_res = sum(e * e for e in resid)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    s2 = ss_res / (n - k)
    se_classical = [math.sqrt(s2 * XtX_inv[i][i]) for i in range(k)]
    return {"coef": beta, "se": se, "se_classical": se_classical, "t": [b / s if s else float("nan") for b, s in zip(beta, se)],
            "r2": r2, "n": n, "resid": resid, "cov": V, "sigma2": s2}
