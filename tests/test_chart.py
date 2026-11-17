import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from agent_tools.chart import SpecError, TYPES, render
from agent_tools.chart.render import fmt, ticks

HERE = os.path.dirname(__file__)
SPECS = json.load(open(os.path.join(HERE, "..", "examples", "specs.json"), encoding="utf-8"))


class Examples(unittest.TestCase):
    def test_every_example_is_valid_svg(self):
        for name, spec in SPECS.items():
            with self.subTest(name):
                svg = render(spec)
                root = ET.fromstring(svg)
                self.assertTrue(root.tag.endswith("svg"))
                self.assertLess(len(svg), 6000, "output should stay compact")

    def test_every_type_covered(self):
        seen = {s["type"] for s in SPECS.values()}
        self.assertEqual(seen, set(TYPES))

    def test_deterministic(self):
        self.assertEqual(render(SPECS["line"]), render(SPECS["line"]))

    def test_json_string_input(self):
        self.assertEqual(render(json.dumps(SPECS["bar"])), render(SPECS["bar"]))

    def test_text_is_escaped(self):
        svg = render({"type": "bar", "title": "<b>&", "data": {"a<b": 1}})
        ET.fromstring(svg)
        self.assertNotIn("<b>", svg)


class Inputs(unittest.TestCase):
    def test_data_forms_agree(self):
        a = render({"data": {"x": 1, "y": 2}})
        b = render({"data": [["x", 1], ["y", 2]]})
        c = render({"x": ["x", "y"], "series": {"": [1, 2]}})
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_series_as_dicts(self):
        render({"series": {"A": {"q1": 1, "q2": 2}, "B": {"q1": 3, "q3": 4}}})

    def test_missing_values(self):
        render({"type": "line", "x": ["a", "b", "c"], "series": {"s": [1, None, 3]}})
        render({"type": "bar", "x": ["a", "b"], "series": {"s": [1, None], "t": [2, 3]}})

    def test_single_value_and_zero(self):
        render({"data": {"only": 0}})
        render({"type": "pie", "data": {"only": 5}})
        render({"type": "donut", "data": {"only": 5}})

    def test_many_categories(self):
        render({"type": "line", "data": {f"d{i}": i % 7 for i in range(200)}})
        render({"type": "bar", "data": {f"category number {i}": i for i in range(30)}})

    def test_pie_groups_other(self):
        svg = render({"type": "pie", "data": {str(i): 10 - i for i in range(10)}})
        self.assertIn(">Other<", svg)

    def test_errors_are_helpful(self):
        cases = [
            ({"type": "nope", "data": {"a": 1}}, "unknown type"),
            ({"data": {"a": "x"}}, "expected a number"),
            ({"x": ["a"], "series": {"s": [1, 2]}}, "labels"),
            ({"type": "pie", "data": {"a": -1}}, ">= 0"),
            ("{bad json", "invalid JSON"),
        ]
        for spec, msg in cases:
            with self.subTest(msg):
                with self.assertRaises(SpecError) as cm:
                    render(spec)
                self.assertIn(msg, str(cm.exception))


class Helpers(unittest.TestCase):
    def test_ticks_are_round(self):
        t, step = ticks(0, 1530000)
        self.assertEqual(t[0], 0)
        self.assertGreaterEqual(t[-1], 1530000)
        self.assertIn(step, (250000, 500000))

    def test_fmt(self):
        self.assertEqual(fmt(1500, pre="$"), "$1.5K")
        self.assertEqual(fmt(-2_000_000), "-2M")
        self.assertEqual(fmt(0.25, suf="%"), "0.25%")
        self.assertEqual(fmt(500000, 250000), "500K")


class Cli(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        env = dict(os.environ, PYTHONPATH=os.path.join(HERE, "..", "src"))
        return subprocess.run([sys.executable, "-m", "agent_tools", *args], input=stdin,
                              capture_output=True, text=True, env=env)

    def test_chart_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "c.svg")
            r = self.run_cli("chart", '{"data":{"a":1}}', "-o", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), out)
            self.assertTrue(os.path.getsize(out) > 0)

    def test_stdin_and_stdout(self):
        r = self.run_cli("chart", "-", "-o", "-", stdin='{"type":"pie","data":{"a":1,"b":2}}')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("<svg"))

    def test_error_exit_code(self):
        r = self.run_cli("chart", '{"type":"nope"}', "-o", "-")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown type", r.stderr)

    def test_list_and_docs(self):
        self.assertIn("chart:", self.run_cli("list").stdout)
        self.assertIn("Types:", self.run_cli("docs", "chart").stdout)


if __name__ == "__main__":
    unittest.main()
