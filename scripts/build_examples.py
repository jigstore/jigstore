"""Regenerate examples/*.svg from examples/specs.json and print the token comparison table.

Tokens are estimated as characters / 4, a common rule of thumb for English and JSON.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agent_tools.chart import render  # noqa: E402

specs = json.load(open(os.path.join(ROOT, "examples", "specs.json"), encoding="utf-8"))
print("| chart | spec tokens | SVG tokens | saved |")
print("|---|---:|---:|---:|")
for name, spec in specs.items():
    svg = render(spec)
    with open(os.path.join(ROOT, "examples", f"{name}.svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    a = len(json.dumps(spec, separators=(",", ":"))) // 4
    b = len(svg) // 4
    print(f"| {name} | {a} | {b} | {100 - 100 * a // b}% |")
