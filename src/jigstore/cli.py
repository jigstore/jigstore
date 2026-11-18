"""Command line entry point. Output is kept to one short line so it costs the agent few tokens."""

from __future__ import annotations

import argparse
import sys
from importlib import resources

from . import CATALOG, __version__


def _read_spec(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    if arg.startswith("@"):
        with open(arg[1:], encoding="utf-8") as f:
            return f.read()
    return arg


def _docs(name: str) -> str:
    return resources.files(f"jigstore.{name}").joinpath("USAGE.md").read_text(encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jigstore", description="Deterministic tools for AI agents.")
    ap.add_argument("--version", action="version", version=f"jigstore {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list tools, one line each")
    sub.add_parser("mcp", help="run the MCP server on stdio")
    d = sub.add_parser("docs", help="print a tool's compact usage")
    d.add_argument("tool", choices=sorted(CATALOG))
    c = sub.add_parser("chart", help="render a chart from a JSON spec")
    c.add_argument("spec", help="JSON string, @file.json, or - for stdin")
    c.add_argument("-o", "--out", default="chart.svg", help="output .svg/.png path, or - for SVG on stdout")
    c.add_argument("--scale", type=float, default=2.0, help="PNG pixel scale (default 2)")
    t = sub.add_parser("table", help="render a table from a JSON spec or a CSV/JSON file")
    t.add_argument("spec", help="JSON string, @file.json, or - for stdin")
    t.add_argument("-o", "--out", default=None, help="output .md/.svg/.png/.html/.csv; default prints Markdown")
    t.add_argument("--scale", type=float, default=2.0, help="PNG pixel scale (default 2)")
    a = ap.parse_args(argv)
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    if a.cmd == "list":
        for k, v in CATALOG.items():
            print(f"{k}: {v}")
        return 0
    if a.cmd == "mcp":
        from .mcp import serve

        return serve()
    if a.cmd == "docs":
        print(_docs(a.tool), end="")
        return 0
    if a.cmd == "chart":
        from .chart import SpecError, render, save

        try:
            spec = _read_spec(a.spec)
            if a.out == "-":
                sys.stdout.write(render(spec) + "\n")
            else:
                print(save(spec, a.out, a.scale))
        except (SpecError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    if a.cmd == "table":
        import os

        from .table import SpecError, render_table, save_table

        try:
            spec = _read_spec(a.spec)
            if a.out in (None, "-"):
                sys.stdout.write(render_table(spec, "md", os.getcwd()))
            else:
                print(save_table(spec, a.out, os.getcwd(), a.scale))
        except (SpecError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    ap.print_help()
    return 1
