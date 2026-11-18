"""Table jig: rows in, a table out as SVG, Markdown, HTML or CSV (PNG via the chart PNG helper).

The spec is a dict (or JSON string). Rows come from "rows" or, when the caller allows it,
from a CSV or JSON file named in "from". Everything a spec puts into the output is escaped
or validated, because specs come from models.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import math
import os
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from ..chart.render import (
    FONT,
    MAX_ABS,
    MAX_TEXT,
    NAMED_PALETTES,
    PALETTES,
    THEMES,
    SpecError,
    _curve,
    _load,
    _mix,
    color,
    fit,
    n,
    on,
    opt_num,
    text_w,
)

FORMATS = ("text", "number", "money", "percent", "date", "bar", "sparkline")
OUTPUTS = ("md", "svg", "html", "csv")
MAX_COLS = 30
MAX_CELLS = 10_000
MAX_TEXT_ROWS = 1000
MAX_IMAGE_ROWS = 200
DEFAULT_IMAGE_ROWS = 25
MAX_FILE_BYTES = 5 * 1024 * 1024
SPARK = "▁▂▃▄▅▆▇█"
NUMERIC = ("number", "money", "percent", "bar")


# ---------------------------------------------------------------- reading input


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coerce(text: str):
    """CSV cells arrive as text; turn plain numbers back into numbers."""
    t = text.strip()
    if t == "":
        return None
    try:
        if t.lstrip("+-").isdigit():
            return int(t)
        f = float(t)
        return f if math.isfinite(f) else t
    except ValueError:
        return t


def _read_file(name, base_dir):
    if base_dir is None:
        raise SpecError('"from" reads a file, which only the CLI and the local MCP server allow; send "rows" instead')
    if not isinstance(name, str) or not name:
        raise SpecError('"from" must be a file path like "data.csv"')
    base = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(base, os.path.expanduser(name)))
    if os.path.commonpath([base, path]) != base:
        raise SpecError(f'"from" must be inside {base}')
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".csv", ".json"):
        raise SpecError('"from" must be a .csv or .json file')
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise SpecError(f'"from" file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB')
        with open(path, encoding="utf-8-sig", newline="") as f:
            raw = f.read()
    except OSError as e:
        raise SpecError(f'"from": cannot read {name!r} ({e.strerror})') from None
    if ext == ".csv":
        reader = csv.reader(io.StringIO(raw))
        try:
            header = next(reader)
        except StopIteration:
            raise SpecError(f'"from": {name!r} is empty') from None
        rows = [[_coerce(c) for c in r] for r in reader if any(c.strip() for c in r)]
        return [h.strip() for h in header], rows
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SpecError(f'"from": invalid JSON in {name!r}: {e.msg}') from None
    if isinstance(data, dict):
        return data.get("columns"), data.get("rows")
    return None, data


def _columns(spec_cols, file_cols, rows):
    """Merge column options from the spec with what the data provides."""
    opts = {}
    order = []
    for c in spec_cols or []:
        if isinstance(c, str):
            c = {"key": c}
        if not isinstance(c, dict) or not isinstance(c.get("key"), str) or not c["key"]:
            raise SpecError('each column must be a name or an object like {"key": "Revenue", "format": "money"}')
        order.append(c["key"])
        opts[c["key"]] = c
    if file_cols:
        for k in file_cols:
            if isinstance(k, dict):
                k = k.get("key")
            if isinstance(k, str) and k not in opts:
                order.append(k)
                opts[k] = {"key": k}
    if not order and rows:
        if isinstance(rows[0], dict):
            for r in rows:
                if isinstance(r, dict):
                    for k in r:
                        if k not in opts:
                            order.append(str(k))
                            opts[str(k)] = {"key": str(k)}
        elif isinstance(rows[0], list):
            for i in range(max(len(r) for r in rows if isinstance(r, list))):
                order.append(str(i + 1))
                opts[str(i + 1)] = {"key": str(i + 1)}
    if not order:
        raise SpecError('give "rows" (a list of objects or lists) and optionally "columns"')
    if len(order) > MAX_COLS:
        raise SpecError(f"too many columns (max {MAX_COLS})")
    return [opts[k] for k in order]


def _matrix(cols, rows, keyed_by_file):
    keys = [c["key"] for c in cols]
    out = []
    for i, r in enumerate(rows):
        if isinstance(r, dict):
            out.append([r.get(k) for k in keys])
        elif isinstance(r, list):
            if keyed_by_file is not None:
                idx = {k: j for j, k in enumerate(keyed_by_file)}
                out.append([r[idx[k]] if k in idx and idx[k] < len(r) else None for k in keys])
            else:
                out.append([r[j] if j < len(r) else None for j in range(len(keys))])
        else:
            raise SpecError(f"row {i + 1}: expected an object or a list")
    return out


# ---------------------------------------------------------------- columns


class Col:
    def __init__(self, o, values):
        self.key = o["key"][:MAX_TEXT]
        self.label = str(o.get("label", self.key))[:MAX_TEXT]
        f = o.get("format")
        if f is None:
            vals = [v for v in values if v is not None]
            if vals and all(isinstance(v, list) for v in vals):
                f = "sparkline"
            elif vals and all(_is_num(v) for v in vals):
                f = "number"
            else:
                f = "text"
        if f not in FORMATS:
            raise SpecError(f'column {self.key!r}: "format" must be one of {", ".join(FORMATS)}')
        self.format = f
        self.prefix = str(o.get("prefix", "$" if f == "money" else ""))[:12]
        self.suffix = str(o.get("suffix", ""))[:12]
        self.compact = o.get("compact", f == "money")
        dec = opt_num(o, "decimals", None, 0, 6, True)
        nums0 = [abs(v) for v in values if _is_num(v) and math.isfinite(v)]
        # compact columns use one unit for every row, chosen from the column's typical size,
        # so values line up: $0.91M, $1.24M, $1.53M (not $905K next to $1.24M)
        self.div, self.unit = 1, ""
        if self.compact and nums0:
            mid = sorted(nums0)[len(nums0) // 2]
            for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
                if mid >= d:
                    self.div, self.unit = d, u
                    break
        if dec is None:
            if f == "percent" or (f == "money" and self.div in (1, 1e6, 1e9, 1e12)):
                dec = 2 if f == "percent" or self.div > 1 or not all(float(v).is_integer() for v in nums0) else 0
            elif f == "money":
                dec = 0  # thousands: $905K
            elif f in ("number", "bar"):
                dec = 2 if self.div > 1 or not all(float(v).is_integer() for v in nums0) else 0
        self.decimals = dec
        align = o.get("align", "right" if f in NUMERIC else "left")
        if align not in ("left", "right", "center"):
            raise SpecError(f'column {self.key!r}: "align" must be left, right or center')
        self.align = align
        c = o.get("color")
        if c not in (None, "sign", "scale"):
            c = color(c, f"column {self.key!r} color")
        self.color = c
        self.width = opt_num(o, "width", None, 40, 600, True)
        # validate and normalise values
        clean = []
        for i, v in enumerate(values):
            clean.append(self._check(v, i))
        self.values = clean
        nums = [v for v in clean if _is_num(v)]
        self.lo = min(nums) if nums else 0.0
        self.hi = max(nums) if nums else 0.0
        self.peak = max((abs(v) for v in nums), default=0.0)

    def _check(self, v, i):
        if v is None:
            return None
        where = f"column {self.key!r} row {i + 1}"
        if self.format in NUMERIC:
            if not _is_num(v) or not math.isfinite(v):
                raise SpecError(f"{where}: expected a number, got {str(v)[:40]!r}")
            if abs(v) > MAX_ABS:
                raise SpecError(f"{where}: {v!r} is too large")
            return float(v) if isinstance(v, float) else v
        if self.format == "sparkline":
            if not isinstance(v, list) or not v or len(v) > 200 or not all(_is_num(x) and math.isfinite(x) for x in v):
                raise SpecError(f"{where}: a sparkline cell must be a list of up to 200 numbers")
            return [float(x) for x in v]
        if self.format == "date":
            s = str(v)[:40]
            try:
                return _dt.date.fromisoformat(s[:10]).isoformat()
            except ValueError:
                raise SpecError(f'{where}: dates must look like "2026-11-19", got {s!r}') from None
        if isinstance(v, (dict, list)):
            raise SpecError(f"{where}: expected text, got a {type(v).__name__}")
        return str(v)[:MAX_TEXT]

    def text(self, v):
        """Display text for a cell."""
        if v is None:
            return ""
        if self.format in ("number", "bar", "money"):
            x = abs(v) / self.div
            q = Decimal(1).scaleb(-self.decimals)
            r = Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP)
            sign = "-" if v < 0 and r else ""
            return f"{sign}{self.prefix}{r:,.{self.decimals}f}{self.unit}{self.suffix}"
        if self.format == "percent":
            # round halves up (22.5 -> 23), which is what people expect in a table
            q = Decimal(1).scaleb(-self.decimals)
            r = Decimal(repr(abs(v))).quantize(q, rounding=ROUND_HALF_UP)
            sign = "-" if v < 0 and r else ""
            return f"{sign}{self.prefix}{r:,.{self.decimals}f}%{self.suffix}"
        if self.format == "sparkline":
            lo, hi = min(v), max(v)
            span = (hi - lo) or 1
            return "".join(SPARK[min(7, int((x - lo) / span * 7.999))] for x in v)
        return str(v)


# ---------------------------------------------------------------- model


class Table:
    def __init__(self, spec, base_dir=None, image=False):
        s = _load(spec)
        self.s = s
        file_cols = None
        rows = s.get("rows")
        if s.get("from") is not None:
            file_cols, rows = _read_file(s["from"], base_dir)
        if not isinstance(rows, list):
            raise SpecError('"rows" must be a list of objects or lists')
        cols = _columns(s.get("columns"), file_cols, rows)
        if len(rows) * len(cols) > MAX_CELLS:
            raise SpecError(f"too many cells (max {MAX_CELLS}); aggregate or filter first")
        keyed = file_cols if file_cols and isinstance(rows[:1] and rows[0], list) else None
        if keyed is not None:
            keyed = [k.get("key") if isinstance(k, dict) else k for k in keyed]
        matrix = _matrix(cols, rows, keyed)
        self.cols = [Col(o, [r[j] for r in matrix]) for j, o in enumerate(cols)]
        self.rows = [list(r) for r in zip(*[c.values for c in self.cols])] if matrix else []
        self.total = self._total(s.get("total"))
        self._sort(s.get("sort"))
        self.hl = self._highlight(s.get("highlight"))
        limit_hi = MAX_IMAGE_ROWS if image else MAX_TEXT_ROWS
        default = DEFAULT_IMAGE_ROWS if image else MAX_TEXT_ROWS
        mx = opt_num(s, "max_rows", default, 1, limit_hi, True)
        self.more = max(0, len(self.rows) - mx)
        self.rows = self.rows[:mx]
        self.title = str(s.get("title", ""))[:MAX_TEXT]
        self.subtitle = str(s.get("subtitle", ""))[:MAX_TEXT]

    def _col(self, key, what):
        for j, c in enumerate(self.cols):
            if c.key == key:
                return j
        raise SpecError(f"{what}: no column named {str(key)[:40]!r}")

    def _total(self, spec):
        if spec is None:
            return None
        if not isinstance(spec, dict):
            raise SpecError('"total" must be an object like {"Region": "Total", "Revenue": "sum"}')
        row = [None] * len(self.cols)
        for k, how in spec.items():
            j = self._col(k, '"total"')
            c = self.cols[j]
            nums = [v for v in c.values if _is_num(v)]
            if how in ("sum", "avg", "min", "max"):
                if c.format not in NUMERIC:
                    raise SpecError(f'"total": column {k!r} is not numeric, so it can\'t use {how!r}')
                if not nums:
                    row[j] = None
                elif how == "sum":
                    total = math.fsum(nums)
                    row[j] = int(total) if all(isinstance(v, int) for v in nums) else total
                elif how == "avg":
                    row[j] = math.fsum(nums) / len(nums)
                else:
                    row[j] = (min if how == "min" else max)(nums)
            else:
                row[j] = ("text", str(how)[:MAX_TEXT])
        return row

    def _sort(self, spec):
        if spec is None:
            return
        if isinstance(spec, str):
            spec = {"by": spec}
        if not isinstance(spec, dict):
            raise SpecError('"sort" must be a column name or {"by": "Revenue", "order": "desc"}')
        j = self._col(spec.get("by"), '"sort"')
        order = spec.get("order", "desc" if self.cols[j].format in NUMERIC else "asc")
        if order not in ("asc", "desc"):
            raise SpecError('"sort" order must be "asc" or "desc"')
        present = [r for r in self.rows if r[j] is not None]
        missing = [r for r in self.rows if r[j] is None]
        present.sort(key=lambda r: r[j] if _is_num(r[j]) else str(r[j]).lower(), reverse=order == "desc")
        self.rows = present + missing

    def _highlight(self, spec):
        if spec is None:
            return set()
        if not isinstance(spec, dict):
            raise SpecError('"highlight" must be {"row": 0} or {"where": {"Region": "East"}}')
        if "row" in spec:
            i = opt_num(spec, "row", None, 0, MAX_TEXT_ROWS, True)
            return {i}
        where = spec.get("where")
        if not isinstance(where, dict) or not where:
            raise SpecError('"highlight" needs "row" or "where"')
        idx = {self._col(k, '"highlight"'): v for k, v in where.items()}
        return {i for i, r in enumerate(self.rows) if all(r[j] == v or str(r[j]) == str(v) for j, v in idx.items())}

    def cell_text(self, j, v):
        if isinstance(v, tuple):
            return v[1]
        return self.cols[j].text(v)


# ---------------------------------------------------------------- outputs


def _md_escape(t):
    t = " ".join(str(t).split())
    t = t.replace("\\", "\\\\").replace("|", "\\|")
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_markdown(t: Table) -> str:
    out = []
    if t.title:
        out.append(f"**{_md_escape(t.title)}**")
        if t.subtitle:
            out.append(f"_{_md_escape(t.subtitle)}_")
        out.append("")
    out.append("| " + " | ".join(_md_escape(c.label) or " " for c in t.cols) + " |")
    marks = {"left": ":--", "right": "--:", "center": ":-:"}
    out.append("|" + "|".join(marks[c.align] for c in t.cols) + "|")
    for r in t.rows:
        out.append("| " + " | ".join(_md_escape(t.cell_text(j, v)) for j, v in enumerate(r)) + " |")
    if t.total:
        cells = [_md_escape(t.cell_text(j, v)) for j, v in enumerate(t.total)]
        out.append("| " + " | ".join(f"**{x}**" if x else "" for x in cells) + " |")
    if t.more:
        out.append("")
        out.append(f"_+ {t.more:,} more rows_")
    return "\n".join(out) + "\n"


def _csv_safe(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v  # stop spreadsheets from running it as a formula
    return v


def to_csv(t: Table) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([_csv_safe(c.label) for c in t.cols])
    for r in t.rows:
        row = []
        for v in r:
            if isinstance(v, list):
                row.append(" ".join(f"{x:g}" for x in v))
            elif isinstance(v, float) and v.is_integer():
                row.append(int(v))
            else:
                row.append(_csv_safe(v) if v is not None else "")
        w.writerow(row)
    if t.total:
        w.writerow(
            [
                _csv_safe(v[1])
                if isinstance(v, tuple)
                else ("" if v is None else (int(v) if isinstance(v, float) and v.is_integer() else v))
                for v in t.total
            ]
        )
    return buf.getvalue()


def _theme(s):
    theme = s.get("theme", "light")
    if theme not in THEMES:
        raise SpecError(f'theme must be "light" or "dark", got {theme!r}')
    pal = s.get("palette", "default")
    if pal == "default":
        p = PALETTES[theme]
    elif pal in NAMED_PALETTES:
        p = NAMED_PALETTES[pal]
    else:
        raise SpecError(f'"palette" must be one of: default, {", ".join(NAMED_PALETTES)}')
    return THEMES[theme], p


def _cell_color(t, th, j, v):
    """(text color, background) for a cell, or (None, None)."""
    c = t.cols[j]
    if not _is_num(v) or c.color is None:
        return None, None
    if c.color == "sign":
        return (th["up"] if v > 0 else th["down"] if v < 0 else None), None
    if c.color == "scale":
        f = (v - c.lo) / (c.hi - c.lo) if c.hi > c.lo else 1.0
        bg = _mix(th["lo"], th["hi"], f)
        return on(bg), bg
    return c.color, None


def to_html(t: Table) -> str:
    th, pal = _theme(t.s)
    font = escape(str(t.s.get("font", FONT))[:120])
    base = f"font-family:{font};font-size:13px;color:{th['fg']};"
    out = [f'<table style="border-collapse:collapse;{base}background:{th["bg"]}">']
    if t.title:
        cap = escape(t.title)
        if t.subtitle:
            cap += f'<br><span style="font-weight:400;color:{th["muted"]};font-size:12px">{escape(t.subtitle)}</span>'
        out.append(f'<caption style="text-align:left;font-weight:600;font-size:15px;padding:0 0 8px">{cap}</caption>')
    out.append("<thead><tr>")
    for c in t.cols:
        out.append(
            f'<th style="text-align:{c.align};padding:7px 12px;border-bottom:2px solid {th["axis"]};'
            f'color:{th["muted"]};font-weight:600">{escape(c.label)}</th>'
        )
    out.append("</tr></thead><tbody>")
    zebra = _mix(th["bg"], th["grid"], 0.45)
    for i, r in enumerate(t.rows):
        bg = _mix(th["bg"], pal[0], 0.14) if i in t.hl else (zebra if i % 2 else th["bg"])
        weight = "font-weight:600;" if i in t.hl else ""
        out.append(f'<tr style="background:{bg};{weight}">')
        for j, v in enumerate(r):
            fg, cbg = _cell_color(t, th, j, v)
            style = f"text-align:{t.cols[j].align};padding:7px 12px;border-bottom:1px solid {th['grid']};"
            if fg:
                style += f"color:{fg};"
            if cbg:
                style += f"background:{cbg};"
            out.append(f'<td style="{style}">{escape(t.cell_text(j, v))}</td>')
        out.append("</tr>")
    if t.total:
        out.append(f'<tr style="font-weight:700;border-top:2px solid {th["fg"]}">')
        for j, v in enumerate(t.total):
            out.append(
                f'<td style="text-align:{t.cols[j].align};padding:7px 12px;border-top:2px solid {th["fg"]}">'
                f"{escape(t.cell_text(j, v))}</td>"
            )
        out.append("</tr>")
    out.append("</tbody></table>")
    if t.more:
        out.append(f'<p style="{base}color:{th["muted"]};margin:6px 0 0">+ {t.more:,} more rows</p>')
    return "".join(out) + "\n"


def to_svg(t: Table) -> str:
    s = t.s
    th, pal = _theme(s)
    fs, hs = 13, 12
    pad = 12
    rowh, headh = 32, 36
    widths = []
    for j, c in enumerate(t.cols):
        cells = [t.cell_text(j, r[j]) for r in t.rows]
        if t.total:
            cells.append(t.cell_text(j, t.total[j]))
        # widths are estimated without font files: allow 10% for bold rows and rounding
        w = max([text_w(c.label, hs) * 1.1] + [text_w(x, fs) * 1.1 for x in cells]) + 2 * pad + 4
        if c.format == "bar":
            w += 90
        if c.format == "sparkline":
            w = max(text_w(c.label, hs) + 2 * pad, 96)
        widths.append(c.width or min(w, 320))
    natural = sum(widths) + 32
    W = opt_num(s, "w", None, 360, 4000, True) or int(min(1200, max(360, natural)))
    room = W - 32
    if sum(widths) > room:  # shrink the widest columns first
        while sum(widths) > room:
            k = widths.index(max(widths))
            if widths[k] <= 60:
                break
            widths[k] -= 2
    x0 = [16]
    for w in widths[:-1]:
        x0.append(x0[-1] + w)
    parts = []
    y = 14
    if t.title:
        parts.append(
            f'<text x="16" y="{y + 16}" font-size="16" font-weight="600">{escape(fit(t.title, 16, W - 32))}</text>'
        )
        y += 24
        if t.subtitle:
            parts.append(f'<text x="16" y="{y + 13}" fill="{th["muted"]}">{escape(fit(t.subtitle, 12, W - 32))}</text>')
            y += 19
        y += 10
    top = y
    tablew = sum(widths)

    def cell_text(j, txt, yy, bold=False, fill=None, size=fs):
        c = t.cols[j]
        maxw = widths[j] - 2 * pad - (90 if c.format == "bar" else 0)
        txt = fit(txt, size, maxw)
        if c.align == "right":
            x, anchor = x0[j] + widths[j] - pad, ' text-anchor="end"'
        elif c.align == "center":
            x, anchor = x0[j] + widths[j] / 2, ' text-anchor="middle"'
        else:
            x, anchor = x0[j] + pad, ""
        attrs = f' font-size="{size}"' if size != 12 else ""
        if bold:
            attrs += ' font-weight="600"'
        if fill:
            attrs += f' fill="{fill}"'
        parts.append(f'<text x="{n(x)}" y="{n(yy)}"{anchor}{attrs}>{escape(txt)}</text>')

    for j, c in enumerate(t.cols):
        cell_text(j, c.label, top + headh / 2 + 4, True, th["muted"], hs)
    parts.append(f'<path d="M16 {n(top + headh - 0.5)}H{n(16 + tablew)}" stroke="{th["axis"]}" stroke-width="1.5"/>')
    y = top + headh
    zebra = _mix(th["bg"], th["grid"], 0.45)
    for i, r in enumerate(t.rows):
        if i in t.hl:
            parts.append(
                f'<rect x="16" y="{n(y)}" width="{n(tablew)}" height="{rowh}" fill="{pal[0]}" fill-opacity=".14"/>'
            )
        elif i % 2 and s.get("zebra", True) is not False:
            parts.append(f'<rect x="16" y="{n(y)}" width="{n(tablew)}" height="{rowh}" fill="{zebra}"/>')
        for j, v in enumerate(r):
            c = t.cols[j]
            fg, cbg = _cell_color(t, th, j, v)
            if cbg:
                parts.append(
                    f'<rect x="{n(x0[j] + 1)}" y="{n(y + 1)}" width="{n(widths[j] - 2)}" '
                    f'height="{rowh - 2}" rx="2" fill="{cbg}"/>'
                )
            if c.format == "bar" and _is_num(v) and c.peak:
                bw = 80 * abs(v) / c.peak
                bx = x0[j] + pad
                parts.append(
                    f'<rect x="{n(bx)}" y="{n(y + 10)}" width="{n(max(1, bw))}" height="12" rx="2" '
                    f'fill="{th["down"] if v < 0 else pal[0]}"/>'
                )
            if c.format == "sparkline" and isinstance(v, list) and len(v) > 1:
                lo, hi = min(v), max(v)
                span = (hi - lo) or 1
                sx, sw = x0[j] + pad, widths[j] - 2 * pad
                pts = [
                    (sx + k * sw / (len(v) - 1), y + rowh - 8 - (val - lo) / span * (rowh - 16))
                    for k, val in enumerate(v)
                ]
                parts.append(
                    f'<path d="{_curve(pts)}" fill="none" stroke="{pal[0]}" '
                    'stroke-width="1.5" stroke-linejoin="round"/>'
                )
                continue
            cell_text(j, t.cell_text(j, v), y + rowh / 2 + 4.5, i in t.hl, fg)
        parts.append(f'<path d="M16 {n(y + rowh - 0.5)}H{n(16 + tablew)}" stroke="{th["grid"]}"/>')
        y += rowh
    if t.total:
        parts.append(f'<path d="M16 {n(y + 0.75)}H{n(16 + tablew)}" stroke="{th["fg"]}" stroke-width="1.5"/>')
        for j, v in enumerate(t.total):
            txt = t.cell_text(j, v)
            if txt:
                cell_text(j, txt, y + rowh / 2 + 5, True)
        y += rowh
    if t.more:
        parts.append(f'<text x="16" y="{n(y + 20)}" fill="{th["muted"]}">+ {t.more:,} more rows</text>')
        y += 28
    H = int(y + 14)
    font = s.get("font")
    if font is not None and (
        not isinstance(font, str) or not all(ch.isalnum() or ch in " ,'.-_" for ch in font) or len(font) > 120
    ):
        raise SpecError('"font" must be a CSS font-family list, like "Inter, sans-serif"')
    title = escape(t.title) if t.title else ""
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{escape(font or FONT, quote=False)}" font-size="12" fill="{th["fg"]}" role="img"'
        + (f' aria-label="{title}"' if title else "")
        + ">"
    )
    bg = s.get("bg", th["bg"])
    bgel = "" if bg == "none" else f'<rect width="100%" height="100%" fill="{color(bg, chr(34) + "bg" + chr(34))}"/>'
    return head + (f"<title>{title}</title>" if title else "") + bgel + "".join(parts) + "</svg>"


# ---------------------------------------------------------------- entry points


def render_table(spec, output="md", base_dir=None) -> str:
    """Render a table spec to "md", "svg", "html" or "csv" text.

    base_dir: folder that "from" may read inside. None (the default) refuses "from", which is
    what a hosted service must do.
    """
    if output not in OUTPUTS:
        raise SpecError(f"output must be one of: {', '.join(OUTPUTS)}")
    t = Table(spec, base_dir, image=output == "svg")
    return {"md": to_markdown, "svg": to_svg, "html": to_html, "csv": to_csv}[output](t)


def save_table(spec, path: str, base_dir=None, scale: float = 2.0) -> str:
    """Render to a file; the extension (.md .svg .png .html .csv) picks the format."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "png":
        from ..chart.png import to_png

        data = to_png(render_table(spec, "svg", base_dir), scale)
        with open(path, "wb") as f:
            f.write(data)
        return path
    if ext not in OUTPUTS:
        raise SpecError(f"output must end in .md, .svg, .png, .html or .csv, got {path!r}")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(render_table(spec, ext, base_dir))
    return path
