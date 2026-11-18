"""Random specs must either render valid SVG or raise SpecError, never anything else.

Uses only the standard library. The seed is fixed so failures are reproducible; set
JIGSTORE_FUZZ_SEED and JIGSTORE_FUZZ_N to explore further.
"""

import os
import random
import unittest
import xml.etree.ElementTree as ET

from jigstore.chart import TYPES, SpecError, render
from jigstore.table import render_table

SEED = int(os.environ.get("JIGSTORE_FUZZ_SEED", "1234"))
N = int(os.environ.get("JIGSTORE_FUZZ_N", "1500"))

ODD_NUMBERS = [0, -0.0, 1, -1, 1e-12, 1e12, 1e15, 1e16, 3.5, float("inf"), float("nan"), True, None, "7", [], {}]
ODD_TEXT = ["", "a", "<b>", '"', "&", "\u202e", "日本語", "x" * 500, None, 5, "#fff", "red"]


def rnum(r):
    return r.choice(ODD_NUMBERS) if r.random() < 0.2 else round(r.uniform(-1e4, 1e4), r.randint(0, 3))


def rtext(r):
    return r.choice(ODD_TEXT) if r.random() < 0.3 else "".join(r.choice("abcXYZ 01_-") for _ in range(r.randint(1, 12)))


def rspec(r):
    t = r.choice(TYPES + ("nope",))
    k = r.randint(0, 12)
    labels = [rtext(r) for _ in range(k)]
    s = {"type": t}
    shape = r.random()
    if t == "scatter":
        s["data"] = [[rnum(r), rnum(r)] + ([rnum(r)] if r.random() < 0.3 else []) for _ in range(k)]
    elif t == "histogram":
        s["values"] = [rnum(r) for _ in range(k)]
        if r.random() < 0.3:
            s["bins"] = rnum(r)
    elif shape < 0.5:
        s["data"] = {str(lab): rnum(r) for lab in labels}
    else:
        s["x"] = labels
        s["series"] = {
            rtext(r) if r.random() < 0.9 else 1: [rnum(r) for _ in range(r.choice([k, k, k + 1]))]
            for _ in range(r.randint(1, 4))
        }
    for key, gen in (
        ("title", rtext), ("subtitle", rtext), ("prefix", rtext), ("suffix", rtext),
        ("w", lambda r: r.choice([40, 160, 640, 5000, -1, "x"])), ("h", lambda r: r.choice([16, 120, 400, 9999])),
        ("stack", lambda r: r.choice([True, "percent", False, "x"])), ("sort", lambda r: r.choice(["asc", "desc", "x"])),
        ("curve", lambda r: r.choice(["linear", "smooth", "step", "x"])), ("legend", lambda r: r.choice(["top", "bottom", "none"])),
        ("ymin", rnum), ("ymax", rnum), ("decimals", lambda r: r.choice([0, 2, 7, "x"])),
        ("refs", lambda r: [r.choice([rnum(r), {"value": rnum(r), "label": rtext(r)}]) for _ in range(r.randint(0, 3))]),
        ("highlight", rtext), ("colors", lambda r: [rtext(r) for _ in range(3)]), ("theme", lambda r: r.choice(["light", "dark", "x"])),
        ("palette", lambda r: r.choice(["colorblind", "mono", "x"])), ("total", rtext), ("hole", rnum), ("labels", lambda r: r.random() < 0.5),
    ):  # fmt: skip
        if r.random() < 0.15:
            s[key] = gen(r)
    return s


class Fuzz(unittest.TestCase):
    def test_random_specs(self):
        r = random.Random(SEED)
        for i in range(N):
            spec = rspec(r)
            try:
                svg = render(spec)
            except SpecError:
                continue
            except Exception as e:  # noqa: BLE001
                self.fail(f"case {i}: {type(e).__name__}: {e}\nspec={spec!r}")
            try:
                ET.fromstring(svg)
            except ET.ParseError as e:
                self.fail(f"case {i}: invalid SVG ({e})\nspec={spec!r}")
            self.assertNotIn("<script", svg)


def rtable(r):
    ncols = r.randint(0, 6)

    # mostly valid column names, with some hostile ones mixed in
    # mostly valid column names and options, with a few hostile ones mixed in
    def rare(good, bad, p=0.04):
        return r.choice(bad) if r.random() < p else good

    keys = [rare(f"c{i}", [rtext(r), 3, "<b>|x", ""]) for i in range(ncols)]
    cols = []
    for k in keys:
        if r.random() < 0.5:
            cols.append(k)
        else:
            cols.append(
                {
                    "key": k,
                    "format": rare(
                        r.choice(("text", "number", "money", "percent", None)), ["date", "bar", "sparkline", "x"], 0.2
                    ),
                    "decimals": rare(r.choice([None, 0, 2]), [9, "x"]),
                    "color": rare(r.choice([None, "sign", "scale", "#fff"]), ["x", 'red" onload="x']),
                    "align": rare(r.choice(["left", "right", "center"]), ["x"]),
                }
            )

    def cell(r, col):
        f = col.get("format") if isinstance(col, dict) else None
        if r.random() < 0.9:  # plausible cells most of the time
            if f in ("number", "money", "percent", "bar"):
                return round(r.uniform(-1e5, 1e5), 2)
            if f == "sparkline":
                return [r.randint(0, 9) for _ in range(r.randint(2, 8))]
            if f == "date":
                return "2026-11-19"
            return r.choice(["North", r.randint(0, 999), 3.5, "a|b"])
        return r.choice([rnum(r), rtext(r), [rnum(r) for _ in range(r.randint(0, 4))], None])

    width = r.choice([ncols, ncols, ncols, ncols + 1])
    rows = [[cell(r, cols[j] if j < len(cols) else None) for j in range(width)] for _ in range(r.randint(0, 30))]
    if r.random() < 0.3:
        rows = [dict(zip([str(k) for k in keys], row)) for row in rows]
    s = {"columns": cols, "rows": rows}
    if r.random() < 0.3 and keys:
        s["total"] = {str(r.choice(keys)): r.choice(["sum", "avg", "min", "max", "Total"])}
    if r.random() < 0.3 and keys:
        s["sort"] = r.choice(
            [str(r.choice(keys)), {"by": str(r.choice(keys)), "order": r.choice(["asc", "desc", "x"])}]
        )
    if r.random() < 0.2:
        s["highlight"] = r.choice([{"row": r.randint(-1, 5)}, {"where": {str(keys[0]) if keys else "a": rtext(r)}}, 5])
    for key, gen in (
        ("title", rtext),
        ("max_rows", rnum),
        ("theme", lambda r: r.choice(["light", "dark", "x"])),
        ("w", lambda r: r.choice([100, 400, 900, "x"])),
        ("from", lambda r: "data.csv"),
    ):
        if r.random() < (0.02 if key == "from" else 0.1):
            s[key] = gen(r)
    return s


class FuzzTable(unittest.TestCase):
    def test_random_tables(self):
        r = random.Random(SEED)
        for i in range(N):
            spec = rtable(r)
            for out in ("md", "svg", "html", "csv"):
                try:
                    text = render_table(spec, out)
                except SpecError:
                    break
                except Exception as e:  # noqa: BLE001
                    self.fail(f"case {i} {out}: {type(e).__name__}: {e}\nspec={spec!r}")
                if out == "svg":
                    try:
                        ET.fromstring(text)
                    except ET.ParseError as e:
                        self.fail(f"case {i}: invalid SVG ({e})\nspec={spec!r}")
                self.assertNotIn("<script", text)


if __name__ == "__main__":
    unittest.main()
