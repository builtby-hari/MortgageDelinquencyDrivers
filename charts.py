"""Hand-written SVG visuals for the README. Standard library only.

Every visual is written twice: a light file and a "-dark" file for GitHub's dark mode.
Files go into docs/:

  banner.svg                       project banner with tagline
  delinquency_over_time.svg        delinquency rate, 1991Q2 to 2026Q2, recessions shaded
  delinquency_vs_unemployment.svg  quarterly change in delinquency vs unemployment change, pre-2020 OLS fit
  coefficients.svg                 unemployment-change coefficient for M1 to M6, with +/-2 Newey-West SE bars
  actual_vs_fitted.svg             model M2 actual and fitted quarterly changes
  driver_correlations.svg          correlation heatmap of the delinquency change and its drivers
  scenario_paths.svg               delinquency history and 9-quarter scenario projections with 95% bands
  sample-output.svg                terminal-window render of `python3 analysis.py`

Usage: python3 charts.py [--out docs]
"""

import argparse
import contextlib
import io
import math
import os
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

import scenario
from analysis import MODELS, PANDEMIC, build_panel, correlation_matrix, report, run_model

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
PRE_2020 = ("1991Q1", "2019Q4")
FONT = "Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, 'Liberation Mono', monospace"
NBSP = " "
SHORT_LABELS = ["Unemp Only", "+ Mortgage Rate", "+ 1Q Lags", "Ex-2020", "Pre-2020", "2021 Onward"]

# NBER business-cycle peaks and troughs, converted to calendar quarters. Hardcoded because the FRED
# USREC series was unavailable when this was written. Swap in USREC from FRED when it is back.
RECESSIONS: List[Tuple[str, str]] = [
    ("1990Q3", "1991Q1"),  # peak Jul 1990, trough Mar 1991
    ("2001Q1", "2001Q4"),  # peak Mar 2001, trough Nov 2001
    ("2007Q4", "2009Q2"),  # peak Dec 2007, trough Jun 2009
    ("2020Q1", "2020Q2"),  # peak Feb 2020, trough Apr 2020
]

# Palette from the README visuals spec. Light: navy and teal. Dark: lighter blues on the same layout.
THEMES = {
    "light": {
        "text": "#334155", "title": "#1f3a5f", "grid": "#cbd5e1", "navy": "#1f3a5f", "teal": "#14b8a6",
        "zero": "#64748b", "shade": "#cbd5e1", "neutral": "#f1f5f9", "strong_text": "#ffffff",
        "window": "#f8fafc", "window_edge": "#cbd5e1", "bar": "#e2e8f0",
    },
    "dark": {
        "text": "#e2e8f0", "title": "#e2e8f0", "grid": "#475569", "navy": "#60a5fa", "teal": "#2dd4bf",
        "zero": "#94a3b8", "shade": "#475569", "neutral": "#1e293b", "strong_text": "#0f172a",
        "window": "#0f172a", "window_edge": "#475569", "bar": "#334155",
    },
}


def nice_ticks(lo: float, hi: float, target: int = 6) -> List[float]:
    if hi - lo <= 0:
        lo, hi = lo - 1.0, hi + 1.0
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw:
            break
    first = math.floor(lo / step + 1e-9)
    last = math.ceil(hi / step - 1e-9)
    return [round(k * step, 10) for k in range(first, last + 1)]


def scaler(d0: float, d1: float, r0: float, r1: float):
    return lambda v: r0 + (v - d0) * (r1 - r0) / (d1 - d0)


def fmt(v: float) -> str:
    return f"{v:.2f}".replace("-", "−")


def mix(c1: str, c2: str, f: float) -> str:
    """Blend hex color c1 toward c2 by fraction f (0 gives c1, 1 gives c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def text(x, y, s, size=12, anchor="start", color="#334155", weight="normal", rotate=None,
         family=FONT, spacing=None) -> str:
    tr = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate is not None else ""
    ls = f' letter-spacing="{spacing}"' if spacing is not None else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{color}" font-weight="{weight}"{ls}{tr}>{escape(s)}</text>')


def wrap(width: int, height: int, title: str, parts: List[str]) -> str:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img">'
            f"<title>{escape(title)}</title>")
    return head + "".join(parts) + "</svg>\n"


def in_pandemic(q: str) -> bool:
    return PANDEMIC[0] <= q <= PANDEMIC[1]


def in_recession(q: str) -> bool:
    return any(lo <= q <= hi for lo, hi in RECESSIONS)


def legend_dot(x, y, color, label, t) -> List[str]:
    return [f'<circle cx="{x + 5}" cy="{y - 4}" r="4.5" fill="{color}" fill-opacity="0.85"/>',
            text(x + 16, y, label, 12, color=t["text"])]


def scatter_svg(rows: List[dict], t: dict) -> str:
    W, H = 800, 580
    L, R, T, B = 90, 50, 110, 74
    pw, ph = W - L - R, H - T - B
    xt = nice_ticks(min(r["d_unemp"] for r in rows), max(r["d_unemp"] for r in rows))
    yt = nice_ticks(min(r["d_delinq"] for r in rows), max(r["d_delinq"] for r in rows))
    sx = scaler(xt[0], xt[-1], L, L + pw)
    sy = scaler(yt[0], yt[-1], T + ph, T)

    fit = run_model(rows, ["d_unemp"], window=PRE_2020)
    a, b = fit["coef"][0], fit["coef"][1]
    pre = [r for r in rows if PRE_2020[0] <= r["quarter"] <= PRE_2020[1]]
    x_lo = min(r["d_unemp"] for r in pre)
    x_hi = max(r["d_unemp"] for r in pre)

    p: List[str] = [
        text(L, 36, "Quarterly Change in Mortgage Delinquency vs. Unemployment Change", 18, color=t["title"],
             weight="bold"),
        text(L, 58, f"Single-family delinquency rate (FRED DRSFRMACBS), {rows[0]['quarter']} to "
                    f"{rows[-1]['quarter']}, n = {len(rows)} quarters", 12),
    ]
    ly = 86
    p += legend_dot(L, ly, t["navy"], "Quarters Before 2020", t)
    p += legend_dot(L + 176, ly, t["teal"], "2020 quarters", t)
    p.append(f'<line x1="{L + 300}" y1="{ly - 4}" x2="{L + 322}" y2="{ly - 4}" stroke="{t["text"]}" stroke-width="2"/>')
    p.append(text(L + 330, ly, f"OLS Fit, Pre-2020 (Slope {fmt(b)})", 12, color=t["text"]))

    for v in yt:
        y = sy(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="{t["grid"]}"/>')
        p.append(text(L - 10, y + 4, fmt(v), 12, "end"))
    for v in xt:
        x = sx(v)
        p.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T + ph}" stroke="{t["grid"]}"/>')
        p.append(text(x, T + ph + 20, fmt(v), 12, "middle"))
    if xt[0] < 0 < xt[-1]:
        p.append(f'<line x1="{sx(0):.1f}" y1="{T}" x2="{sx(0):.1f}" y2="{T + ph}" stroke="{t["zero"]}" stroke-dasharray="4 3"/>')
    if yt[0] < 0 < yt[-1]:
        p.append(f'<line x1="{L}" y1="{sy(0):.1f}" x2="{L + pw}" y2="{sy(0):.1f}" stroke="{t["zero"]}" stroke-dasharray="4 3"/>')
    p.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="{t["text"]}"/>')
    p.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + ph}" stroke="{t["text"]}"/>')
    p.append(text(L + pw / 2, H - 22, "Change in Unemployment Rate, Quarter Over Quarter (pp)", 13, "middle"))
    p.append(text(24, T + ph / 2, "Change in Delinquency Rate, Quarter Over Quarter (pp)", 13, "middle",
                  rotate=-90))

    for r in sorted(rows, key=lambda r: in_pandemic(r["quarter"])):
        color = t["teal"] if in_pandemic(r["quarter"]) else t["navy"]
        opacity = 0.95 if in_pandemic(r["quarter"]) else 0.75
        p.append(f'<circle cx="{sx(r["d_unemp"]):.1f}" cy="{sy(r["d_delinq"]):.1f}" r="3.8" '
                 f'fill="{color}" fill-opacity="{opacity}">'
                 f'<title>{escape(r["quarter"])}</title></circle>')

    p.append(f'<line x1="{sx(x_lo):.1f}" y1="{sy(a + b * x_lo):.1f}" x2="{sx(x_hi):.1f}" '
             f'y2="{sy(a + b * x_hi):.1f}" stroke="{t["text"]}" stroke-width="2"/>')
    return wrap(W, H, "Scatter of Quarterly Change in Delinquency Rate Against Change in Unemployment Rate", p)


def line_svg(rows: List[dict], t: dict) -> str:
    W, H = 800, 440
    L, R, T, B = 70, 30, 110, 60
    pw, ph = W - L - R, H - T - B
    vals = [r["delinquency"] for r in rows]
    yt = nice_ticks(min(vals), max(vals))
    sy = scaler(yt[0], yt[-1], T + ph, T)
    slot = pw / len(rows)

    def x_of(i: int) -> float:
        return L + (i + 0.5) * slot

    p: List[str] = [
        text(L, 36, "Single-Family Mortgage Delinquency Rate, 1991Q2 to 2026Q2", 18, color=t["title"], weight="bold"),
        text(L, 58, "FRED DRSFRMACBS, quarterly. Shaded quarters are NBER recessions.", 12),
    ]
    p.append(f'<rect x="{L + 300}" y="{86 - 10}" width="14" height="12" fill="{t["shade"]}" fill-opacity="0.8"/>')
    p.append(text(L + 322, 86, "NBER Recession Quarter", 12))
    p.append(f'<line x1="{L + 480}" y1="{86 - 4}" x2="{L + 502}" y2="{86 - 4}" stroke="{t["navy"]}" stroke-width="2.2"/>')
    p.append(text(L + 510, 86, "Delinquency Rate (%)", 12))

    for v in yt:
        y = sy(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="{t["grid"]}"/>')
        p.append(text(L - 10, y + 4, f"{v:.0f}" if v == int(v) else f"{v:.1f}", 12, "end"))

    for i, r in enumerate(rows):
        if in_recession(r["quarter"]):
            p.append(f'<rect x="{L + i * slot:.2f}" y="{T}" width="{slot:.2f}" height="{ph}" '
                     f'fill="{t["shade"]}" fill-opacity="0.8"/>')

    p.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="{t["text"]}"/>')
    for i, r in enumerate(rows):
        if r["quarter"].endswith("Q1") and int(r["quarter"][:4]) % 5 == 0:
            p.append(text(x_of(i), T + ph + 20, r["quarter"][:4], 12, "middle"))

    pts = " ".join(f"{x_of(i):.1f},{sy(r['delinquency']):.1f}" for i, r in enumerate(rows))
    p.append(f'<polyline points="{pts}" fill="none" stroke="{t["navy"]}" stroke-width="2.2" stroke-linejoin="round"/>')
    return wrap(W, H, "Single-Family Mortgage Delinquency Rate Over Time with Recessions Shaded", p)


def coef_svg(rows: List[dict], t: dict) -> str:
    W, H = 800, 500
    L, R, T, B = 90, 30, 110, 84
    pw, ph = W - L - R, H - T - B
    results = []
    for title, xcols, excl, window in MODELS:
        res = run_model(rows, xcols, excl, window)
        i = res["names"].index("d_unemp")
        results.append((res["coef"][i], res["se"][i] * 2))
    lows = [b - h for b, h in results] + [0.0]
    highs = [b + h for b, h in results] + [0.0]
    yt = nice_ticks(min(lows), max(highs))
    sy = scaler(yt[0], yt[-1], T + ph, T)
    slot = pw / len(results)

    p: List[str] = [
        text(L, 36, "Unemployment-Change Coefficient Across Models M1 to M6", 18, color=t["title"], weight="bold"),
        text(L, 58, "Dot: OLS coefficient. Bar: plus or minus 2 Newey-West standard errors (4 lags).", 12),
        text(L, 76, "Dependent variable: quarterly change in delinquency rate (pp).", 12),
    ]
    for v in yt:
        y = sy(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="{t["grid"]}"/>')
        p.append(text(L - 10, y + 4, fmt(v), 12, "end"))
    p.append(f'<line x1="{L}" y1="{sy(0):.1f}" x2="{L + pw}" y2="{sy(0):.1f}" stroke="{t["zero"]}" stroke-dasharray="4 3"/>')
    p.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="{t["text"]}"/>')
    p.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + ph}" stroke="{t["text"]}"/>')

    for i, ((b, h), desc) in enumerate(zip(results, SHORT_LABELS)):
        mid = MODELS[i][0].split()[0]
        cx = L + (i + 0.5) * slot
        lo_y, hi_y, b_y = sy(b - h), sy(b + h), sy(b)
        p.append(f'<line x1="{cx:.1f}" y1="{lo_y:.1f}" x2="{cx:.1f}" y2="{hi_y:.1f}" stroke="{t["navy"]}" stroke-width="2.5"/>')
        for yy in (lo_y, hi_y):
            p.append(f'<line x1="{cx - 8:.1f}" y1="{yy:.1f}" x2="{cx + 8:.1f}" y2="{yy:.1f}" stroke="{t["navy"]}" stroke-width="2.5"/>')
        p.append(f'<circle cx="{cx:.1f}" cy="{b_y:.1f}" r="5.5" fill="{t["navy"]}"/>')
        p.append(text(cx + 12, b_y + 4, fmt(b), 12, "start", weight="bold"))
        p.append(text(cx, T + ph + 22, mid, 13, "middle", weight="bold"))
        p.append(text(cx, T + ph + 40, desc, 11, "middle"))

    p.append(text(L + pw / 2, H - 14, "Model", 13, "middle"))
    p.append(text(24, T + ph / 2, "Coefficient on Change in Unemployment (pp per pp)", 13, "middle", rotate=-90))
    return wrap(W, H, "Unemployment-Change Coefficient with Plus or Minus 2 Newey-West SE for Models M1 to M6", p)


def fitted_svg(rows: List[dict], t: dict) -> str:
    W, H = 800, 440
    L, R, T, B = 80, 30, 110, 60
    pw, ph = W - L - R, H - T - B
    res = run_model(rows, ["d_unemp", "d_rate"])
    quarters, actual, fitted = res["quarters"], res["y"], res["fitted"]
    yt = nice_ticks(min(actual + fitted), max(actual + fitted))
    sy = scaler(yt[0], yt[-1], T + ph, T)
    slot = pw / len(quarters)

    def x_of(i: int) -> float:
        return L + (i + 0.5) * slot

    p: List[str] = [
        text(L, 36, "Actual vs. Fitted Quarterly Change in Delinquency (Model M2)", 18, color=t["title"], weight="bold"),
        text(L, 58, f"Full sample, n = {res['n']}, R² = {res['r2']:.3f}. Fitted values come from the same OLS "
                    "fit as M2.", 12),
    ]
    p.append(f'<line x1="{L}" y1="{86 - 4}" x2="{L + 22}" y2="{86 - 4}" stroke="{t["navy"]}" stroke-width="1.6"/>')
    p.append(text(L + 30, 86, "Actual", 12))
    p.append(f'<line x1="{L + 100}" y1="{86 - 4}" x2="{L + 122}" y2="{86 - 4}" stroke="{t["teal"]}" stroke-width="2.4"/>')
    p.append(text(L + 130, 86, "Fitted", 12))

    for v in yt:
        y = sy(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="{t["grid"]}"/>')
        p.append(text(L - 10, y + 4, fmt(v), 12, "end"))
    p.append(f'<line x1="{L}" y1="{sy(0):.1f}" x2="{L + pw}" y2="{sy(0):.1f}" stroke="{t["zero"]}" stroke-dasharray="4 3"/>')
    p.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="{t["text"]}"/>')
    for i, q in enumerate(quarters):
        if q.endswith("Q1") and int(q[:4]) % 5 == 0:
            p.append(text(x_of(i), T + ph + 20, q[:4], 12, "middle"))
    p.append(text(L + pw / 2, H - 14, "Quarter", 13, "middle"))
    p.append(text(22, T + ph / 2, "Change in Delinquency, q/q (pp)", 13, "middle", rotate=-90))

    def line(vals: List[float], color: str, width: float) -> str:
        pts = " ".join(f"{x_of(i):.1f},{sy(v):.1f}" for i, v in enumerate(vals))
        return (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" '
                f'stroke-linejoin="round" stroke-linecap="round"/>')

    p.append(line(actual, t["navy"], 1.6))
    p.append(line(fitted, t["teal"], 2.4))
    return wrap(W, H, "Actual and Fitted Quarterly Change in Delinquency Rate, Model M2", p)


def heatmap_svg(rows: List[dict], t: dict) -> str:
    cols = ["d_delinq", "d_unemp", "d_rate", "d_unemp_lag", "d_rate_lag"]
    labels = ["Δ Delinquency", "Δ Unemployment", "Δ Mortgage Rate", "Δ Unemp, Lag 1", "Δ Rate, Lag 1"]
    n_used = sum(1 for r in rows if all(r[c] is not None for c in cols))
    M = correlation_matrix(rows, cols)
    W, H = 800, 520
    L, T = 170, 118
    cw, ch = 104, 56
    p: List[str] = [
        text(40, 36, "Correlation of the Delinquency Change with Its Drivers", 18, color=t["title"], weight="bold"),
        text(40, 58, f"Pearson correlation, n = {n_used} quarters with all five series present.", 12),
    ]
    for j, lab in enumerate(labels):
        p.append(text(L + j * cw + cw / 2, T - 12, lab, 12, "middle"))
    for i, lab in enumerate(labels):
        p.append(text(L - 12, T + i * ch + ch / 2 + 4, lab, 12, "end"))
    for i in range(len(cols)):
        for j in range(len(cols)):
            v = M[i][j]
            color = mix(t["neutral"], t["teal"] if v >= 0 else t["navy"], abs(v))
            tc = t["strong_text"] if abs(v) > 0.55 else t["text"]
            x, y = L + j * cw, T + i * ch
            p.append(f'<rect x="{x}" y="{y}" width="{cw - 3}" height="{ch - 3}" rx="4" fill="{color}"/>')
            p.append(text(x + (cw - 3) / 2, y + (ch - 3) / 2 + 5, fmt(v), 13, "middle", tc,
                          weight="bold" if i == j else "normal"))
    gy = T + len(cols) * ch + 26
    gw = 3 * cw
    p.append(f'<defs><linearGradient id="corrgrad" x1="0" x2="1" y1="0" y2="0">'
             f'<stop offset="0" stop-color="{t["navy"]}"/>'
             f'<stop offset="0.5" stop-color="{t["neutral"]}"/>'
             f'<stop offset="1" stop-color="{t["teal"]}"/></linearGradient></defs>')
    p.append(f'<rect x="{L}" y="{gy}" width="{gw}" height="12" rx="3" fill="url(#corrgrad)"/>')
    p.append(text(L, gy + 28, "−1 (Negative)", 12, "start"))
    p.append(text(L + gw / 2, gy + 28, "0", 12, "middle"))
    p.append(text(L + gw, gy + 28, "+1 (Positive)", 12, "end"))
    return wrap(W, H, "Correlation Heatmap of the Delinquency Change and Its Drivers", p)


def scenario_svg(rows: List[dict], proj: Dict[str, List[dict]], t: dict) -> str:
    W, H = 800, 440
    L, R, T, B = 70, 130, 110, 60
    pw, ph = W - L - R, H - T - B
    hist = rows[-20:]
    n = len(hist) + scenario.HORIZON
    yt = nice_ticks(0, max(max(p["hi"] for p in ps) for ps in proj.values()))
    sy = scaler(yt[0], yt[-1], T + ph, T)
    x_of = lambda i: L + (i + 0.5) * pw / n
    colors = {"baseline": t["zero"], "adverse": t["navy"], "severely_adverse": t["teal"]}
    p: List[str] = [
        text(L, 36, "Delinquency Rate Under Illustrative Scenarios", 18, color=t["title"], weight="bold"),
        text(L, 58, f"Last 20 quarters observed, then {scenario.HORIZON} projected. Bands are 95%. Paths are illustrative inputs.", 12),
    ]
    for v in yt:
        p.append(f'<line x1="{L}" y1="{sy(v):.1f}" x2="{L + pw}" y2="{sy(v):.1f}" stroke="{t["grid"]}"/>')
        p.append(text(L - 10, sy(v) + 4, f"{v:.0f}" if v == int(v) else f"{v:.1f}", 12, "end"))
    p.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="{t["text"]}"/>')
    for i, r in enumerate(hist):
        if r["quarter"].endswith("Q1"):
            p.append(text(x_of(i), T + ph + 20, r["quarter"][:4], 12, "middle"))
    pts = " ".join(f"{x_of(i):.1f},{sy(r['delinquency']):.1f}" for i, r in enumerate(hist))
    p.append(f'<polyline points="{pts}" fill="none" stroke="{t["text"]}" stroke-width="2.2" stroke-linejoin="round"/>')
    k = len(hist)
    for name, ps in proj.items():
        col = colors.get(name, t["navy"])
        xs = [x_of(k - 1)] + [x_of(k + j) for j in range(len(ps))]
        last = hist[-1]["delinquency"]
        up = [(x, sy(v)) for x, v in zip(xs, [last] + [q["hi"] for q in ps])]
        dn = [(x, sy(v)) for x, v in zip(xs, [last] + [q["lo"] for q in ps])][::-1]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in up + dn)
        p.append(f'<polygon points="{poly}" fill="{col}" fill-opacity="0.12"/>')
        line = " ".join(f"{x:.1f},{sy(v):.1f}" for x, v in zip(xs, [last] + [q["level"] for q in ps]))
        p.append(f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round"/>')
        p.append(text(xs[-1] + 8, sy(ps[-1]["level"]) + 4, name.replace("_", " ").title(), 12, color=col, weight="bold"))
    return wrap(W, H, "Projected Delinquency Rate Under Baseline, Adverse and Severely Adverse Illustrative Scenarios", p)


def banner_svg(t: dict) -> str:
    W, H = 1200, 240
    p: List[str] = [
        text(80, 104, "Mortgage Delinquency Drivers", 52, color=t["title"], weight="bold", spacing=1),
        f'<line x1="80" y1="130" x2="260" y2="130" stroke="{t["teal"]}" stroke-width="4" stroke-linecap="round"/>',
        text(80, 176, "What Moves the Mortgage Delinquency Rate: OLS with Newey-West Errors", 24, color=t["text"]),
        text(80, 214, "FRED Quarterly Panel, 1991 to 2026  ·  Standard Library Only", 15, color=t["text"]),
    ]
    return wrap(W, H, "Mortgage Delinquency Drivers Banner", p)


def terminal_svg(lines: List[str], t: dict) -> str:
    W = 900
    LH = 17
    head = 40
    H = head + 26 + len(lines) * LH + 22
    p: List[str] = [
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["window"]}" '
        f'stroke="{t["window_edge"]}"/>',
        f'<path d="M0.5 12.5 Q0.5 0.5 12.5 0.5 L{W - 12.5} 0.5 Q{W - 0.5} 0.5 {W - 0.5} 12.5 '
        f'L{W - 0.5} {head} L0.5 {head} Z" fill="{t["bar"]}"/>',
    ]
    for k, color in enumerate(("#f87171", "#fbbf24", "#34d399")):
        p.append(f'<circle cx="{22 + k * 20}" cy="{head / 2}" r="6" fill="{color}"/>')
    y = head + 26
    for line in lines:
        prompt = ""
        body = line
        if line.startswith("$ "):
            prompt = f'<tspan fill="{t["teal"]}">$</tspan>'
            body = line[1:]
        p.append(f'<text x="22" y="{y}" font-family="{MONO}" font-size="13" fill="{t["text"]}" '
                 f'xml:space="preserve">{prompt}{escape(body.replace(" ", NBSP))}</text>')
        y += LH
    return wrap(W, H, "Terminal Output of python3 analysis.py", p)


def sample_output_lines(rows: List[dict]) -> List[str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(rows)
    out = buf.getvalue().rstrip("\n").split("\n")
    return ["$ python3 analysis.py"] + out + ["Wrote panel.csv"]


def build_all(rows: List[dict]) -> Dict[str, Dict[str, str]]:
    """Return {name: {"light": svg, "dark": svg}} for every visual."""
    proj = scenario.compute(scenario.DEFAULT_SCENARIO_FILE)[3]
    makers = {
        "banner": banner_svg,
        "delinquency_over_time": lambda t: line_svg(rows, t),
        "delinquency_vs_unemployment": lambda t: scatter_svg(rows, t),
        "coefficients": lambda t: coef_svg(rows, t),
        "actual_vs_fitted": lambda t: fitted_svg(rows, t),
        "driver_correlations": lambda t: heatmap_svg(rows, t),
        "scenario_paths": lambda t: scenario_svg(rows, {n: r["proj"] for n, r in proj.items()}, t),
    }
    out: Dict[str, Dict[str, str]] = {}
    for name, make in makers.items():
        out[name] = {theme: make(THEMES[theme]) for theme in THEMES}
    lines = sample_output_lines(rows)
    out["sample-output"] = {theme: terminal_svg(lines, THEMES[theme]) for theme in THEMES}
    return out


def generate(out_dir: str = DOCS_DIR) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    rows = build_panel()
    paths = {}
    for name, variants in build_all(rows).items():
        for theme, svg in variants.items():
            fname = f"{name}.svg" if theme == "light" else f"{name}-dark.svg"
            path = os.path.join(out_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            paths[fname] = path
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DOCS_DIR)
    args = parser.parse_args()
    for path in generate(args.out).values():
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
