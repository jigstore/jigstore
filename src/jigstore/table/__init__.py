"""Table jig: rows (or a CSV/JSON file) in; Markdown, SVG, PNG, HTML or CSV out."""

from ..chart.render import SpecError
from .render import FORMATS, OUTPUTS, render_table, save_table

__all__ = ["render_table", "save_table", "SpecError", "FORMATS", "OUTPUTS"]
