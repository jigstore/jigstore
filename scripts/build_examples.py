"""Regenerate examples/ from examples/specs.json (charts) and examples/tables.json (tables),
and print the token and time comparison tables used in the README and on the website.

Tokens are estimated as characters / 4, a common rule of thumb for English and JSON.
Time assumes a model writes 50 to 100 output tokens a second; rendering itself takes
well under a millisecond and is ignored.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")
sys.path.insert(0, os.path.join(ROOT, "src"))

from jigstore.chart import render  # noqa: E402
from jigstore.table import render_table  # noqa: E402


def tokens(text):
    return len(text) // 4


def secs(tok):
    return f"{tok / 100:.1f} to {tok / 50:.1f} s"


specs = json.load(open(os.path.join(EX, "specs.json"), encoding="utf-8"))
print("| chart | spec tokens | SVG tokens | saved | time by hand | time with spec |")
print("|---|---:|---:|---:|---:|---:|")
for name, spec in specs.items():
    svg = render(spec)
    with open(os.path.join(EX, f"{name}.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    a = tokens(json.dumps(spec, separators=(",", ":")))
    b = tokens(svg)
    print(f"| {name} | {a} | {b} | {100 - 100 * a // b}% | {secs(b)} | {secs(a)} |")

tables = json.load(open(os.path.join(EX, "tables.json"), encoding="utf-8"))
print()
print("| table | spec tokens | Markdown by hand | HTML by hand | saved vs HTML |")
print("|---|---:|---:|---:|---:|")
for name, spec in tables.items():
    for ext in ("svg", "md"):
        with open(os.path.join(EX, f"{name}.{ext}"), "w", encoding="utf-8") as f:
            f.write(render_table(spec, ext, EX))
    full = dict(spec, max_rows=1000)
    a = tokens(json.dumps(spec, separators=(",", ":")))
    md = tokens(render_table(full, "md", EX))
    html = tokens(render_table(full, "html", EX))
    print(f"| {name} | {a} | {md} | {html} | {100 - 100 * a // html}% |")
