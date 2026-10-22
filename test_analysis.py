import importlib.util
import math
import os
import random
import tempfile
import unittest
import xml.etree.ElementTree as ET

import charts
from analysis import quarter_key, quarterly_mean, build_panel, run_model, pearson, diagnostics_report, correlation_matrix
from diagnostics import durbin_watson, adf, adf_critical
from ols import ols, inverse, matmul, default_nw_lags


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


class PivotToleranceTests(unittest.TestCase):
    def test_well_scaled_singular_matrix_rejected(self):
        with self.assertRaises(ValueError):
            inverse([[1.0, 2.0], [2.0, 4.0]])

    def test_small_but_invertible_matrix_accepted(self):
        inv = inverse([[1e-8, 0.0], [0.0, 1e-8]])
        self.assertAlmostEqual(inv[0][0] * 1e-8, 1.0, places=9)

    def test_badly_scaled_near_singular_matrix_rejected(self):
        # Pivot after elimination is about 1e-5, above the old absolute 1e-12 but tiny next to 1e8.
        with self.assertRaises(ValueError):
            inverse([[1e8, 1e8], [1e8, 1e8 * (1 + 1e-13)]])


class PanelTests(unittest.TestCase):
    def test_gap_in_quarters_raises_naming_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, dates in (("DRSFRMACBS", ["2020-01-01", "2020-04-01", "2020-10-01", "2021-01-01"]),
                                ("UNRATE", ["2020-01-01", "2020-04-01", "2020-10-01", "2021-01-01"]),
                                ("MORTGAGE30US", ["2020-01-02", "2020-04-02", "2020-10-01", "2021-01-07"])):
                with open(os.path.join(tmp, name + ".csv"), "w") as f:
                    f.write("DATE,VALUE\n" + "".join(f"{d},1.0\n" for d in dates))
            with self.assertRaisesRegex(ValueError, "2020Q3"):
                build_panel(tmp)

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
              "actual_vs_fitted", "driver_correlations", "scenario_paths", "sample-output"]

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


class OlsValidationTests(unittest.TestCase):
    def test_default_lag_rule(self):
        self.assertEqual(default_nw_lags(140), 4)
        self.assertEqual(default_nw_lags(100), 4)
        self.assertEqual(default_nw_lags(22), 2)

    def test_classical_se_hand_computed(self):
        # y = 1..5 on a constant: s2 = 10 / 4 = 2.5, Var = s2 / n = 0.5
        res = ols([[1.0]] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], nw_lags=0)
        self.assertAlmostEqual(res["se_classical"][0] ** 2, 0.5, places=12)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            ols([[1.0, 2.0]], [1.0])                        # n <= k
        with self.assertRaises(ValueError):
            ols([[1.0]] * 3, [1.0, 2.0])                    # length mismatch
        with self.assertRaises(ValueError):
            ols([[1.0], [1.0, 2.0], [1.0]], [1.0, 2.0, 3.0])  # ragged
        with self.assertRaises(ValueError):
            ols([[1.0]] * 3, [1.0, 2.0, 3.0], index=[1, 1, 2])  # duplicate index
        with self.assertRaises(ValueError):
            ols([[1.0]] * 3, [1.0, 2.0, 3.0], nw_lags=-1)


class DiagnosticsTests(unittest.TestCase):
    def test_durbin_watson_known_values(self):
        self.assertAlmostEqual(durbin_watson([1, -1, 1, -1]), 3.0)   # alternating: 12 / 4
        self.assertAlmostEqual(durbin_watson([1, 1, 1, 1]), 0.0)     # no change
        with self.assertRaises(ValueError):
            durbin_watson([0, 0, 0])

    def test_durbin_watson_skips_gaps(self):
        # Pairs (0,1), (3,4), (4,5) are consecutive; the jump 1 to 3 is skipped. Numerator 4 + 0 + 4, denominator 5.
        resid = [1, -1, 1, 1, -1]
        self.assertAlmostEqual(durbin_watson(resid, [0, 1, 3, 4, 5]), (4 + 0 + 4) / 5)
        with self.assertRaises(ValueError):
            durbin_watson([1, 2, 3], [0, 2, 4])

    def test_report_runs_on_real_panel(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            diagnostics_report(build_panel())
        self.assertIn("Durbin-Watson", buf.getvalue())

    def test_adf_rejects_unit_root_for_stationary_ar1(self):
        rng = random.Random(1)
        y = [0.0]
        for _ in range(400):
            y.append(0.5 * y[-1] + rng.gauss(0, 1))
        self.assertTrue(adf(y, lags=2)["reject_unit_root"]["1%"])

    def test_adf_does_not_reject_random_walk(self):
        rng = random.Random(2)
        y = [0.0]
        for _ in range(400):
            y.append(y[-1] + rng.gauss(0, 1))
        res = adf(y, lags=2)
        self.assertFalse(res["reject_unit_root"]["5%"])
        self.assertEqual(res["n"], 398)  # 400 changes minus 2 lags

    def test_adf_critical_approaches_asymptotic_values(self):
        cv = adf_critical(10 ** 9)
        for lvl, expected in (("1%", -3.43035), ("5%", -2.86154), ("10%", -2.56677)):
            self.assertAlmostEqual(cv[lvl], expected, delta=1e-4)

    def test_adf_critical_is_more_negative_in_small_samples(self):
        small, mid, asym = adf_critical(25), adf_critical(100), adf_critical(10 ** 9)
        self.assertLess(small["5%"], mid["5%"])
        self.assertLess(mid["5%"], asym["5%"])
        self.assertLess(small["1%"], small["5%"])
        self.assertLess(small["5%"], small["10%"])

    def test_adf_reports_critical_values_for_its_sample_size(self):
        rng = random.Random(4)
        y = [0.0]
        for _ in range(60):
            y.append(y[-1] + rng.gauss(0, 1))
        res = adf(y, lags=2)
        self.assertEqual(res["critical"], adf_critical(res["n"]))

    def test_empty_and_constant_inputs_raise_value_error(self):
        with self.assertRaises(ValueError):
            ols([], [])
        with self.assertRaises(ValueError):
            pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])


class CliTests(unittest.TestCase):
    def test_panel_flag_writes_csv_with_header(self):
        import analysis
        import contextlib, io
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.csv")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analysis.main(["--panel", path])
            with open(path) as f:
                header = f.readline().strip()
        self.assertEqual(header, "quarter,delinquency,d_delinq,d_unemp,d_rate,d_unemp_lag,d_rate_lag")
        self.assertIn("Wrote", buf.getvalue())

    def test_default_run_writes_ignored_output_folder(self):
        import analysis
        import contextlib, io
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    analysis.main([])
                with open(os.path.join("output", "panel.csv")) as f:
                    fields = f.read().replace("\n", ",").split(",")
            finally:
                os.chdir(cwd)
        self.assertFalse(os.path.exists(os.path.join(tmp, "panel.csv")))
        self.assertNotIn("-0.0", fields)

    def test_diagnostics_flag_adds_section(self):
        import analysis
        import contextlib, io
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(buf):
                analysis.main(["--panel", os.path.join(tmp, "p.csv"), "--diagnostics"])
        self.assertIn("Diagnostics", buf.getvalue())

    def test_unknown_flag_exits(self):
        import analysis
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                analysis.main(["--no-such-flag"])


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class FetchTests(unittest.TestCase):
    def test_fetch_returns_decoded_text(self):
        import fetch_fred
        calls = []

        def opener(url, timeout):
            calls.append((url, timeout))
            return _FakeResponse("DATE,VALUE\n2020-01-01,3.5\n".encode("utf-8"))

        text = fetch_fred.fetch("UNRATE", opener=opener)
        self.assertEqual(text, "DATE,VALUE\n2020-01-01,3.5\n")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("id=UNRATE"))
        self.assertEqual(calls[0][1], 30)

    def test_fetch_retries_then_succeeds(self):
        import fetch_fred
        import urllib.error
        from unittest import mock
        attempts = []

        def opener(url, timeout):
            attempts.append(url)
            if len(attempts) <= 2:
                raise urllib.error.URLError("temporary failure")
            return _FakeResponse(b"ok")

        with mock.patch("fetch_fred.time.sleep") as sleep:
            text = fetch_fred.fetch("UNRATE", opener=opener)
        self.assertEqual(text, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_fetch_reraises_after_all_retries(self):
        import fetch_fred
        import urllib.error
        from unittest import mock
        attempts = []

        def opener(url, timeout):
            attempts.append(url)
            raise urllib.error.URLError("down")

        with mock.patch("fetch_fred.time.sleep") as sleep:
            with self.assertRaises(urllib.error.URLError):
                fetch_fred.fetch("UNRATE", opener=opener)
        self.assertEqual(len(attempts), len(fetch_fred.RETRY_DELAYS) + 1)
        self.assertEqual(sleep.call_count, len(fetch_fred.RETRY_DELAYS))


if __name__ == "__main__":
    unittest.main()


class ScenarioTests(unittest.TestCase):
    # Toy model y = 0.5 + 2*d_unemp - 1*d_rate; V = diag(0.01, 0.04, 0.09); sigma2 = 0.25.
    RES = {"coef": [0.5, 2.0, -1.0], "cov": [[0.01, 0, 0], [0, 0.04, 0], [0, 0, 0.09]], "sigma2": 0.25}
    START = {"delinquency": 3.0, "unemployment": 5.0, "mortgage_rate": 6.0, "d_unemp": 0.0, "d_rate": 0.0}
    PATH = [{"quarter": "2027Q1", "unemployment": 5.5, "mortgage_rate": 6.0},
            {"quarter": "2027Q2", "unemployment": 5.5, "mortgage_rate": 5.5}]

    def test_projection_matches_hand_calculation(self):
        import scenario
        p = scenario.project(self.RES, ["d_unemp", "d_rate"], self.START, self.PATH)
        # step 1: 0.5 + 2*0.5 - 0 = 1.5; step 2: 0.5 + 0 + 0.5 = 1.0
        self.assertAlmostEqual(p[0]["level"], 4.5)
        self.assertAlmostEqual(p[1]["level"], 5.5)
        # h=1: c=(1,0.5,0): 0.01 + 0.25*0.04 + 0.25 = 0.27. h=2: c=(2,0.5,-0.5): 0.04+0.01+0.0225+0.5 = 0.5725
        self.assertAlmostEqual(p[0]["se"] ** 2, 0.27)
        self.assertAlmostEqual(p[1]["se"] ** 2, 0.5725)
        self.assertAlmostEqual(p[1]["hi"], 5.5 + 1.96 * math.sqrt(0.5725))

    def test_lagged_terms_use_previous_step(self):
        import scenario
        res = {"coef": [0.0, 1.0], "cov": [[0.0, 0], [0, 0.0]], "sigma2": 0.0}
        start = dict(self.START, d_unemp=0.3)
        p = scenario.project(res, ["d_unemp_lag"], start, self.PATH)
        self.assertAlmostEqual(p[0]["d_delinq"], 0.3)   # last observed change
        self.assertAlmostEqual(p[1]["d_delinq"], 0.5)   # first projected change

    def test_bands_widen_with_horizon(self):
        import scenario
        rows = build_panel()
        title, xcols, excl, window = scenario.model_by_id("M4")
        res = run_model(rows, xcols, excl, window)
        scen = scenario.load_scenarios(scenario.DEFAULT_SCENARIO_FILE, rows[-1]["quarter"])
        for path in scen.values():
            ses = [p["se"] for p in scenario.project(res, xcols, scenario.start_state(rows), path)]
            self.assertEqual(ses, sorted(ses))
            self.assertLess(ses[0], ses[-1])

    def test_loss_math(self):
        import scenario
        # 2% and 4% delinquent, 20% roll, 25% LGD: (2 + 4) * 0.2 * 0.25 = 0.3% of portfolio
        self.assertAlmostEqual(scenario.cumulative_loss_rate([2.0, 4.0], 0.20, 0.25), 0.3)
        self.assertEqual(scenario.cumulative_loss_rate([-1.0], 0.20, 0.25), 0.0)
        proj = [{"lo": 1.0, "level": 2.0, "hi": 3.0}]
        t = scenario.loss_table(proj, 0.20, 0.25, 1000.0)
        self.assertAlmostEqual(t["level"]["amount"], 1.0)   # 2% * 0.2 * 0.25 = 0.1% of 1,000
        self.assertLess(t["lo"]["amount"], t["hi"]["amount"])

    def _write(self, tmp, lines):
        path = os.path.join(tmp, "s.csv")
        with open(path, "w") as f:
            f.write("scenario,quarter,unemployment,mortgage_rate\n" + "\n".join(lines) + "\n")
        return path

    def test_scenario_file_validation(self):
        import scenario
        qs = [scenario.quarter_label(scenario.quarter_index("2026Q2") + i) for i in range(1, 10)]
        good = [f"base,{q},4.3,6.4" for q in qs]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(scenario.load_scenarios(self._write(tmp, good), "2026Q2")["base"]), 9)
            with self.assertRaisesRegex(ValueError, "missing quarters 2028Q3"):
                scenario.load_scenarios(self._write(tmp, good[:-1]), "2026Q2")
            with self.assertRaisesRegex(ValueError, "appears twice"):
                scenario.load_scenarios(self._write(tmp, good + good[:1]), "2026Q2")
            with self.assertRaisesRegex(ValueError, "unexpected quarters 2029Q1"):
                scenario.load_scenarios(self._write(tmp, good + ["base,2029Q1,4,6"]), "2026Q2")
            with self.assertRaisesRegex(ValueError, "must be numbers"):
                scenario.load_scenarios(self._write(tmp, ["base,2026Q3,abc,6"]), "2026Q2")

    def test_rebase_shifts_to_observed_levels(self):
        import scenario
        with tempfile.TemporaryDirectory() as tmp:
            qs = ["2026Q2"] + [scenario.quarter_label(scenario.quarter_index("2026Q2") + i) for i in range(1, 10)]
            f = self._write(tmp, [f"s,{q},{5 + i * 0.5},{6 - i * 0.1}" for i, q in enumerate(qs)])
            plain = scenario.load_scenarios(f, "2026Q2")["s"]
            self.assertAlmostEqual(plain[0]["unemployment"], 5.5)
            shifted = scenario.load_scenarios(f, "2026Q2", rebase={"unemployment": 4.0, "mortgage_rate": 6.5})["s"]
            self.assertAlmostEqual(shifted[0]["unemployment"], 4.5)
            self.assertAlmostEqual(shifted[0]["mortgage_rate"], 6.4)
            with self.assertRaisesRegex(ValueError, "missing quarters 2026Q2"):
                scenario.load_scenarios(self._write(tmp, [r for r in open(f).read().splitlines()[2:]]), "2026Q2",
                                        rebase={"unemployment": 4.0, "mortgage_rate": 6.5})

    def test_fed_2026_file_loads_and_projects(self):
        import scenario
        path = os.path.join("scenarios", "fed_2026.csv")
        for rebase in (False, True):
            title, n, start, res = scenario.compute(path, rebase=rebase)
            self.assertEqual(set(res), {"baseline", "severely_adverse"})
            sev, base = res["severely_adverse"]["proj"], res["baseline"]["proj"]
            self.assertEqual(len(sev), 9)
            self.assertGreater(sev[-1]["level"], base[-1]["level"])
            # README loss range table: low <= point <= high, and severe above baseline at every point
            for r in res.values():
                L = r["loss"]
                self.assertLessEqual(L["lo"]["pct"], L["level"]["pct"])
                self.assertLessEqual(L["level"]["pct"], L["hi"]["pct"])
            for key in ("lo", "level", "hi"):
                self.assertGreater(res["severely_adverse"]["loss"][key]["pct"], res["baseline"]["loss"][key]["pct"])
        self.assertAlmostEqual(sev[0]["unemployment"], 8.2 + start["unemployment"] - 7.2)

    def test_cli_prints_projection_and_rejects_bad_file(self):
        import analysis
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            analysis.main(["--scenario", "scenarios/illustrative.csv"])
        self.assertIn("not a CECL model", buf.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            bad = self._write(tmp, ["base,2026Q3,4.3,6.4"])
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                analysis.main(["--scenario", bad])
