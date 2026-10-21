import importlib.util
import os
import random
import tempfile
import unittest
import xml.etree.ElementTree as ET

import charts
from analysis import quarter_key, quarterly_mean, build_panel, run_model, pearson, correlation_matrix
from ols import ols, inverse, matmul


class OlsTests(unittest.TestCase):
    def test_inverse_of_known_matrix(self):
        inv = inverse([[4.0, 7.0], [2.0, 6.0]])
        expected = [[0.6, -0.7], [-0.2, 0.4]]
        for i in range(2):
            for j in range(2):
                self.assertAlmostEqual(inv[i][j], expected[i][j], places=10)

    def test_inverse_times_matrix_is_identity(self):
        A = [[2.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 4.0]]
        I = matmul(A, inverse(A))
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(I[i][j], 1.0 if i == j else 0.0, places=9)

    def test_recovers_known_coefficients(self):
        rng = random.Random(1)
        X, y = [], []
        for _ in range(500):
            x1, x2 = rng.gauss(0, 1), rng.gauss(0, 1)
            X.append([1.0, x1, x2])
            y.append(2 + 3 * x1 - 1.5 * x2 + rng.gauss(0, 0.5))
        res = ols(X, y, nw_lags=4)
        self.assertAlmostEqual(res["coef"][0], 2.0, delta=0.1)
        self.assertAlmostEqual(res["coef"][1], 3.0, delta=0.1)
        self.assertAlmostEqual(res["coef"][2], -1.5, delta=0.1)
        self.assertGreater(res["r2"], 0.9)

    def test_newey_west_wider_than_naive_for_autocorrelated_errors(self):
        # AR(1) errors with strong positive persistence: HAC SEs should exceed the naive ones
        rng = random.Random(3)
        X, y, e = [], [], 0.0
        for _ in range(400):
            x = rng.gauss(0, 1)
            e = 0.9 * e + rng.gauss(0, 1)
            X.append([1.0, x])
            y.append(1.0 + 0.5 * x + e)
        hac = ols(X, y, nw_lags=8)["se"][1]
        naive = ols(X, y, nw_lags=0)["se"][1]
        self.assertGreater(hac, naive)


class NeweyWestReferenceTests(unittest.TestCase):
    def test_hand_computed_mean_with_one_lag(self):
        # Constant-only regression on y = 1..5. Residuals are -2,-1,0,1,2.
        # sum e^2 = 10 and sum e_t e_(t-1) = 4. Bartlett weight at lag 1 with L=1 is 0.5.
        # S = 10 + 0.5 * 2 * 4 = 14, and Var = S / n^2 = 14 / 25 = 0.56.
        res = ols([[1.0]] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], nw_lags=1)
        self.assertAlmostEqual(res["se"][0] ** 2, 0.56, places=12)

    def test_bartlett_weights_with_two_lags(self):
        # Same data, L=2. Lag-2 products: e2e0 + e3e1 + e4e2 = 0 + (-1) + 0 = -1. Weights: 2/3 and 1/3.
        # S = 10 + (2/3)*2*4 + (1/3)*2*(-1) = 10 + 16/3 - 2/3 = 14.6667, Var = S/25.
        res = ols([[1.0]] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], nw_lags=2)
        self.assertAlmostEqual(res["se"][0] ** 2, (10 + 16 / 3 - 2 / 3) / 25, places=12)

    def test_gap_in_index_is_not_bridged(self):
        # Same values, but the index skips one period after the third row. The lag-1 pair across the
        # gap must be dropped, so the standard error differs from the contiguous case.
        y = [1.0, 2.0, 4.0, 5.0, 6.0]
        contiguous = ols([[1.0]] * 5, y, nw_lags=1, index=[0, 1, 2, 3, 4])["se"][0]
        gapped = ols([[1.0]] * 5, y, nw_lags=1, index=[0, 1, 2, 4, 5])["se"][0]
        self.assertNotAlmostEqual(contiguous, gapped, places=6)


class PanelTests(unittest.TestCase):
    def test_quarter_key(self):
        self.assertEqual(quarter_key("2020-01-01"), "2020Q1")
        self.assertEqual(quarter_key("2020-03-31"), "2020Q1")
        self.assertEqual(quarter_key("2020-10-01"), "2020Q4")

    def test_quarterly_mean_averages_within_quarter(self):
        series = [("2021-01-01", 3.0), ("2021-02-01", 4.0), ("2021-03-01", 5.0), ("2021-04-01", 10.0)]
        m = quarterly_mean(series)
        self.assertAlmostEqual(m["2021Q1"], 4.0)
        self.assertAlmostEqual(m["2021Q2"], 10.0)

    def test_panel_changes_and_lags_line_up(self):
        rows = build_panel()
        self.assertTrue(rows[0]["quarter"] < rows[-1]["quarter"])
        for i in range(1, 10):
            self.assertAlmostEqual(rows[i]["d_delinq"], rows[i]["delinquency"] - rows[i - 1]["delinquency"], places=3)
            self.assertAlmostEqual(rows[i]["d_unemp_lag"], rows[i - 1]["d_unemp"], places=3)
        self.assertIsNone(rows[0]["d_unemp_lag"])

    def test_window_restricts_sample(self):
        rows = build_panel()
        pre = run_model(rows, ["d_unemp"], window=("1991Q1", "2019Q4"))
        self.assertGreater(pre["n"], 0)
        self.assertLess(pre["n"], run_model(rows, ["d_unemp"])["n"])

    def test_pandemic_exclusion_drops_2020(self):
        rows = build_panel()
        full = run_model(rows, ["d_unemp"], exclude_pandemic=False)
        ex = run_model(rows, ["d_unemp"], exclude_pandemic=True)
        self.assertEqual(ex["n"], full["n"] - 4)


class CorrelationTests(unittest.TestCase):
    def test_pearson_perfect_and_opposite(self):
        self.assertAlmostEqual(pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), 1.0, places=12)
        self.assertAlmostEqual(pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]), -1.0, places=12)

    def test_correlation_matrix_has_unit_diagonal_and_is_symmetric(self):
        rows = build_panel()
        cols = ["d_delinq", "d_unemp", "d_rate", "d_unemp_lag", "d_rate_lag"]
        M = correlation_matrix(rows, cols)
        for i in range(len(cols)):
            self.assertAlmostEqual(M[i][i], 1.0, places=12)
            for j in range(len(cols)):
                self.assertAlmostEqual(M[i][j], M[j][i], places=12)


class ModelOutputTests(unittest.TestCase):
    def test_fitted_plus_residual_equals_actual(self):
        rows = build_panel()
        res = run_model(rows, ["d_unemp", "d_rate"])
        self.assertEqual(len(res["quarters"]), res["n"])
        for y, f, e in zip(res["y"], res["fitted"], res["resid"]):
            self.assertAlmostEqual(f + e, y, places=12)


class ChartTests(unittest.TestCase):
    CHARTS = ["banner", "delinquency_over_time", "delinquency_vs_unemployment", "coefficients",
              "actual_vs_fitted", "driver_correlations", "sample-output"]

    def test_every_chart_has_light_and_dark_valid_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = charts.generate(tmp)
            self.assertEqual(len(paths), 2 * len(self.CHARTS))
            for name in self.CHARTS:
                for fname in (f"{name}.svg", f"{name}-dark.svg"):
                    path = os.path.join(tmp, fname)
                    self.assertTrue(os.path.exists(path), fname)
                    root = ET.parse(path).getroot()
                    self.assertTrue(root.tag.endswith("svg"), fname)

    def test_dark_variants_use_dark_palette_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            charts.generate(tmp)
            for name in self.CHARTS:
                with open(os.path.join(tmp, f"{name}.svg"), encoding="utf-8") as f:
                    light = f.read()
                with open(os.path.join(tmp, f"{name}-dark.svg"), encoding="utf-8") as f:
                    dark = f.read()
                dark_accents = (charts.THEMES["dark"]["navy"], charts.THEMES["dark"]["teal"])
                self.assertTrue(any(c in dark for c in dark_accents), name)
                self.assertFalse(any(c in light for c in dark_accents), name)

    def test_recession_quarters_are_shaded_in_line_chart(self):
        rows = build_panel()
        svg = charts.line_svg(rows, charts.THEMES["light"])
        shaded = sum(1 for r in rows if charts.in_recession(r["quarter"]))
        # one extra match: the legend swatch uses the same shade fill
        self.assertEqual(svg.count(f'fill="{charts.THEMES["light"]["shade"]}" fill-opacity="0.8"'), shaded + 1)
        self.assertGreater(shaded, 0)

    def test_terminal_output_matches_report(self):
        rows = build_panel()
        lines = charts.sample_output_lines(rows)
        self.assertEqual(lines[0], "$ python3 analysis.py")
        self.assertTrue(any(line.startswith("M5") and "n=115" in line for line in lines))

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_matplotlib_pngs_are_written(self):
        import plots_mpl
        with tempfile.TemporaryDirectory() as tmp:
            paths = plots_mpl.make_all(tmp)
            self.assertEqual(len(paths), 5)
            for path in paths:
                with open(path, "rb") as f:
                    self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
