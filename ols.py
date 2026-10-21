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
    M = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            raise ValueError("matrix is singular")
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
    return [row[n:] for row in M]


def ols(X: Matrix, y: Sequence[float], nw_lags: int = 4, index: Optional[Sequence[int]] = None):
    """Return dict with coef, se (Newey-West), t, r2, n.

    `index` gives each row's position in time (for example, a quarter number). Newey-West lag products
    then pair only rows exactly `lag` periods apart, so gaps from dropped periods are not bridged.
    If omitted, rows are treated as consecutive.
    """
    n, k = len(X), len(X[0])
    if index is None:
        index = list(range(n))
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
    return {"coef": beta, "se": se, "t": [b / s if s else float("nan") for b, s in zip(beta, se)],
            "r2": r2, "n": n, "resid": resid}
