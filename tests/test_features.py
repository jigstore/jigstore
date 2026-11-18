import time
import unittest
import xml.etree.ElementTree as ET

from jigstore.chart import SpecError, render

CATS = {"North": 12, "South": 9, "East": 15, "West": 7}


def ok(spec):
    svg = render(spec)
    ET.fromstring(svg)
    return svg


class NewTypes(unittest.TestCase):
    def test_waterfall_total_and_colors(self):
        svg = ok({"type": "waterfall", "data": {"Start": 10, "Cost": -4, "Gain": 3}, "total": "Net"})
        self.assertIn(">Net<", svg)
        self.assertIn(">+3<", svg)
        self.assertIn(">-4<", svg)
        self.assertIn(">9<", svg)  # 10 - 4 + 3

    def test_funnel_shares(self):
        svg = ok({"type": "funnel", "data": {"Visit": 1000, "Signup": 250, "Paid": 50}})
        self.assertIn(">25%<", svg)
        self.assertIn(">5%<", svg)
        with self.assertRaises(SpecError):
            render({"type": "funnel", "data": {"a": -1}})

    def test_heatmap_grid(self):
        svg = ok({"type": "heatmap", "x": ["a", "b"], "series": {"r1": [1, 2], "r2": [3, None]}})
        self.assertIn(">r2<", svg)
        ok({"type": "heatmap", "x": ["a", "b"], "series": {"r": [1, 2]}, "colors": ["#ffffff", "#000000"]})

    def test_sparkline_is_small_and_bare(self):
        svg = ok({"type": "sparkline", "data": [1, 3, 2, 5]})
        self.assertIn('width="120" height="32"', svg)
        self.assertNotIn("<text", svg)
        self.assertNotIn("<rect", svg)  # transparent by default
        with self.assertRaises(SpecError):
            render({"type": "sparkline", "data": [1]})


class Options(unittest.TestCase):
    def test_highlight_dims_the_rest(self):
        svg = ok({"data": CATS, "highlight": "East"})
        self.assertEqual(svg.count("#cbd2d9"), 3)

    def test_refs_draw_a_labelled_line(self):
        svg = ok({"data": CATS, "refs": [{"value": 20, "label": "Target"}]})
        self.assertIn("stroke-dasharray", svg)
        self.assertIn(">Target<", svg)
        self.assertIn(">20<", svg)  # axis grew to include the ref
        ok({"type": "hbar", "data": CATS, "refs": [10]})

    def test_percent_stack(self):
        svg = ok({"type": "bar", "stack": "percent", "x": ["a", "b"], "series": {"p": [1, 3], "q": [1, 1]}})
        self.assertIn(">100%<", svg)
        ok({"type": "area", "stack": "percent", "x": ["a", "b"], "series": {"p": [1, 3], "q": [1, 1]}})

    def test_curves(self):
        base = {"type": "line", "x": ["a", "b", "c", "d"], "series": {"s": [1, 4, 2, 3]}}
        self.assertIn("C", ok(dict(base, curve="smooth")).split('stroke-width="2.25"')[0].split('d="')[-1])
        self.assertIn("H", ok(dict(base, curve="step")).split('stroke-width="2.25"')[0].split('d="')[-1])
        with self.assertRaises(SpecError):
            render(dict(base, curve="wavy"))

    def test_legend_positions(self):
        spec = {"x": ["a", "b"], "series": {"p": [1, 2], "q": [2, 1]}}
        self.assertNotIn(">p<", ok(dict(spec, legend="none")))
        self.assertIn(">p<", ok(dict(spec, legend="bottom")))

    def test_grid_off_ymin_ymax_decimals(self):
        svg = ok({"data": CATS, "grid": False, "ymin": 0, "ymax": 40, "decimals": 1})
        self.assertNotIn("#e5e7eb", svg)
        self.assertIn(">40.0<", svg)

    def test_palettes(self):
        self.assertIn("#0072b2", ok({"data": CATS, "palette": "colorblind"}))
        with self.assertRaises(SpecError):
            render({"data": CATS, "palette": "neon"})

    def test_scaled_suffix_is_not_compacted_again(self):
        svg = ok({"data": {"a": 1240}, "prefix": "$", "suffix": "K"})
        self.assertIn("$1,240K", svg)
        self.assertNotIn("KK", svg)


class Security(unittest.TestCase):
    """Specs come from models and can be steered by untrusted text."""

    def test_color_injection_is_refused(self):
        for bad in ['red" onload="alert(1)', "#fff/><script>", "url(javascript:x)", 5]:
            with self.subTest(bad):
                with self.assertRaises(SpecError):
                    render({"data": CATS, "colors": [bad]})
                with self.assertRaises(SpecError):
                    render({"data": CATS, "bg": bad})

    def test_font_injection_is_refused(self):
        with self.assertRaises(SpecError):
            render({"data": CATS, "font": 'x" onload="alert(1)'})
        ok({"data": CATS, "font": "Inter, sans-serif"})

    def test_text_never_becomes_markup(self):
        evil = '<script>alert(1)</script>" onmouseover="x'
        svg = ok(
            {"title": evil, "subtitle": evil, "data": {evil: 1}, "prefix": evil, "refs": [{"value": 1, "label": evil}]}
        )
        self.assertNotIn("<script", svg)
        self.assertNotIn('" onmouseover', svg)

    def test_non_finite_and_huge_numbers(self):
        for v in (float("inf"), float("-inf"), float("nan"), 1e300):
            with self.subTest(v):
                with self.assertRaises(SpecError):
                    render({"data": {"a": v}})

    def test_bad_option_types_are_spec_errors(self):
        for spec in (
            {"w": "wide"},
            {"h": True},
            {"decimals": 99},
            {"hole": 5, "type": "donut"},
            {"bins": "x", "type": "histogram", "values": [1, 2]},
            {"legend": "left"},
        ):
            with self.subTest(spec):
                with self.assertRaises(SpecError):
                    render(dict({"data": {"a": 1}}, **spec))

    def test_long_labels_are_fast(self):
        t = time.perf_counter()
        ok({"title": "x" * 200_000, "data": {"y" * 200_000: 1, "b": 2}})
        self.assertLess(time.perf_counter() - t, 1.0)


if __name__ == "__main__":
    unittest.main()
