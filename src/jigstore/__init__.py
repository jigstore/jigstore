"""Jigstore: deterministic tools ("jigs") for AI agents, so the model writes a short spec
instead of generating the whole output token by token."""

__version__ = "0.1.0"

# name -> one-line summary. `jigstore list` prints this; `jigstore docs <name>` prints usage.
CATALOG = {
    "chart": "bar/hbar/line/area/scatter/pie/donut/histogram from a JSON spec -> SVG or PNG",
}
