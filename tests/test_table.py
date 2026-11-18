import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from jigstore.table import SpecError, render_table, save_table

HERE = os.path.dirname(__file__)
ROWS = [
    {"Region": "North", "Revenue": 1240000, "Growth": 12, "Deals": 40},
    {"Region": "South", "Revenue": 905000, "Growth": -3.25, "Deals": 31},
    {"Region": "East", "Revenue": 1530000, "Growth": 22.5, "Deals": 52},
]
SPEC = {
    "columns": ["Region", {"key": "Revenue", "format": "money"}, {"key": "Growth", "format": "percent"}, "Deals"],
    "rows": ROWS,
}


class Inputs(unittest.TestCase):
    def test_objects_and_lists_agree(self):
        lists = {"columns": SPEC["columns"], "rows": [list(r.values()) for r in ROWS]}
        self.assertEqual(render_table(SPEC), render_table(lists))

    def test_columns_inferred(self):
        md = render_table({"rows": ROWS})
        self.assertIn("| Region | Revenue | Growth | Deals |", md)
        self.assertIn("|:--|--:|--:|--:|", md)  # numbers right-aligned

    def test_from_csv_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "q3.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Region", "Revenue"])
                w.writerows([["North", "1240000"], ["South", "905000"]])
            with open(os.path.join(d, "q3.json"), "w") as f:
                json.dump([{"Region": "North", "Revenue": 1240000}, {"Region": "South", "Revenue": 905000}], f)
            spec = {
                "columns": ["Region", {"key": "Revenue", "format": "money"}],
                "total": {"Region": "Total", "Revenue": "sum"},
            }
            a = render_table(dict(spec, **{"from": "q3.csv"}), "md", d)
            b = render_table(dict(spec, **{"from": "q3.json"}), "md", d)
            self.assertEqual(a, b)
            self.assertIn("**$2.15M**", a)

    def test_from_is_refused_without_a_base_dir(self):
        with self.assertRaises(SpecError) as cm:
            render_table({"from": "q3.csv"})
        self.assertIn("only the CLI", str(cm.exception))

    def test_from_cannot_escape_the_base_dir(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ("../secret.csv", "/etc/hosts", "x.txt"):
                with self.subTest(bad):
                    with self.assertRaises(SpecError):
                        render_table({"from": bad}, "md", d)


class Formatting(unittest.TestCase):
    def test_percent_takes_whole_numbers_with_two_decimals(self):
        md = render_table(SPEC)
        self.assertIn("12.00%", md)
        self.assertIn("-3.25%", md)
        cols = [SPEC["columns"][0], {"key": "Growth", "format": "percent", "decimals": 0}]
        self.assertIn("| 23% |", render_table({"columns": cols, "rows": ROWS}))

    def test_money_is_compact_with_one_unit_per_column(self):
        md = render_table(SPEC)
        self.assertIn("$1.24M", md)
        self.assertIn("$0.91M", md)  # same unit as the rest of the column, so it lines up
        self.assertIn(
            "$905K", render_table({"columns": [{"key": "a", "format": "money"}], "rows": [[905000], [12000]]})
        )

    def test_totals(self):
        md = render_table(dict(SPEC, total={"Region": "Total", "Revenue": "sum", "Deals": "avg"}))
        self.assertIn("**$3.68M**", md)  # 3,675,000 rounds half up
        self.assertIn("**41**", md)
        with self.assertRaises(SpecError):
            render_table(dict(SPEC, total={"Region": "sum"}))

    def test_sort_and_highlight(self):
        md = render_table(dict(SPEC, sort="Revenue", highlight={"where": {"Region": "North"}}))
        lines = [ln for ln in md.splitlines() if ln.startswith("| ") and "Region" not in ln]
        self.assertTrue(lines[0].startswith("| East"))
        svg = render_table(dict(SPEC, sort={"by": "Region", "order": "asc"}, highlight={"row": 0}), "svg")
        self.assertIn('fill-opacity=".14"', svg)

    def test_sparkline_and_bar(self):
        spec = {
            "columns": ["Name", {"key": "Trend", "format": "sparkline"}, {"key": "Share", "format": "bar"}],
            "rows": [["a", [1, 3, 2, 5], 40], ["b", [5, 4, 3, 1], 60]],
        }
        self.assertIn("▁▄▂█", render_table(spec))
        ET.fromstring(render_table(spec, "svg"))

    def test_dates(self):
        spec = {"columns": [{"key": "Day", "format": "date"}], "rows": [["2026-11-19"], ["2026-11-20T10:00:00"]]}
        self.assertIn("2026-11-20", render_table(spec))
        with self.assertRaises(SpecError):
            render_table({"columns": [{"key": "Day", "format": "date"}], "rows": [["yesterday"]]})

    def test_max_rows(self):
        rows = [{"n": i} for i in range(40)]
        svg = render_table({"rows": rows}, "svg")
        self.assertIn("+ 15 more rows", svg)  # images default to 25
        self.assertNotIn("more rows", render_table({"rows": rows}))  # text formats keep them


class Safety(unittest.TestCase):
    EVIL = '<script>alert(1)</script>|x" onload="y'

    def test_markdown_escapes(self):
        md = render_table({"rows": [{"a": self.EVIL}], "title": self.EVIL})
        self.assertNotIn("<script", md)
        self.assertIn("\\|x", md)

    def test_html_and_svg_escape(self):
        spec = {"rows": [{self.EVIL: self.EVIL}], "title": self.EVIL}
        for out in ("html", "svg"):
            with self.subTest(out):
                text = render_table(spec, out)
                self.assertNotIn("<script", text)
                self.assertNotIn('" onload', text)
        ET.fromstring(render_table(spec, "svg"))

    def test_csv_formula_injection(self):
        text = render_table({"rows": [{"a": '=HYPERLINK("http://x")', "b": "+1", "c": "@x", "d": -5}]}, "csv")
        row = next(csv.reader(io.StringIO(text.splitlines()[1])))
        self.assertEqual(row[:3], ['\'=HYPERLINK("http://x")', "'+1", "'@x"])
        self.assertEqual(row[3], "-5")  # real negative numbers stay numbers

    def test_bad_color_refused(self):
        with self.assertRaises(SpecError):
            render_table({"columns": [{"key": "a", "color": 'red" onload="x'}], "rows": [[1]]})

    def test_limits(self):
        with self.assertRaises(SpecError):
            render_table({"rows": [{str(i): 1 for i in range(31)}]})
        with self.assertRaises(SpecError):
            render_table({"rows": [{"a": 1, "b": 2}] * 5001})
        with self.assertRaises(SpecError):
            render_table({"columns": [{"key": "n", "format": "number"}], "rows": [["x"]]})


class Files(unittest.TestCase):
    def test_usage_docs_fit_the_token_budget(self):
        from importlib import resources

        from jigstore import CATALOG

        for name in CATALOG:
            with self.subTest(name):
                text = resources.files(f"jigstore.{name}").joinpath("USAGE.md").read_text(encoding="utf-8")
                self.assertLess(len(text), 1200, "USAGE.md must stay under ~300 tokens")

    def test_every_format(self):
        with tempfile.TemporaryDirectory() as d:
            for ext in ("md", "svg", "html", "csv"):
                p = save_table(SPEC, os.path.join(d, f"t.{ext}"))
                self.assertGreater(os.path.getsize(p), 0)

    def test_cli_prints_markdown_by_default(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "..", "src"))
        r = subprocess.run(
            [sys.executable, "-m", "jigstore", "table", json.dumps(SPEC)], capture_output=True, text=True, env=env
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("| Region"))
        bad = subprocess.run(
            [sys.executable, "-m", "jigstore", "table", '{"rows": 5}'], capture_output=True, text=True, env=env
        )
        self.assertEqual(bad.returncode, 2)
        self.assertIn("error:", bad.stderr)


if __name__ == "__main__":
    unittest.main()
