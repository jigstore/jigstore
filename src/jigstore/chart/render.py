"""Zero-dependency SVG chart renderer built for agents.

Input is a small dict ("spec"); output is a compact, self-contained SVG string.
"""

from __future__ import annotations

import json
import math
import re
from html import escape


class SpecError(ValueError):
    """Raised for an invalid chart spec. Messages are one line and say how to fix it."""


PALETTES = {
    "light": [
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#59a14f",
        "#edc948",
        "#b07aa1",
        "#ff9da7",
        "#9c755f",
        "#bab0ac",
    ],
    "dark": [
        "#6aa5e8",
        "#f9a14a",
        "#f0716f",
        "#8fd3cc",
        "#7cc56f",
        "#f2d45c",
        "#c79bd0",
        "#ffb3bb",
        "#c19a7f",
        "#cfc6c2",
    ],
}
# Named palettes, chosen with "palette". "colorblind" is Okabe-Ito.
NAMED_PALETTES = {
    "colorblind": ["#0072b2", "#e69f00", "#009e73", "#d55e00", "#cc79a7", "#56b4e9", "#f0e442", "#999999"],
    "mono": ["#1f4e79", "#2e75b6", "#5b9bd5", "#9dc3e6", "#c5dbef", "#e2edf8"],
    "warm": ["#e8590c", "#f59f00", "#d6336c", "#c92a2a", "#fab005", "#a61e4d"],
    "cool": ["#1971c2", "#0ca678", "#5f3dc4", "#1098ad", "#3b5bdb", "#2b8a3e"],
}
THEMES = {
    "light": {
        "bg": "#ffffff", "fg": "#1f2937", "muted": "#6b7280", "grid": "#e5e7eb", "axis": "#9ca3af",
        "dim": "#cbd2d9", "up": "#3b9a57", "down": "#d64545", "lo": "#eef4fb", "hi": "#1f4e79",
    },
    "dark": {
        "bg": "#0f172a", "fg": "#e2e8f0", "muted": "#94a3b8", "grid": "#1e293b", "axis": "#475569",
        "dim": "#3b4a5f", "up": "#5fc27e", "down": "#f0716f", "lo": "#1e293b", "hi": "#6aa5e8",
    },
}  # fmt: skip
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MAX_POINTS = 10000
MAX_ABS = 1e15  # larger numbers can't be labelled usefully
MAX_TEXT = 300  # characters kept from any label, before fitting
TYPES = (
    "bar", "hbar", "line", "area", "scatter", "pie", "donut", "histogram",
    "waterfall", "funnel", "heatmap", "sparkline",
)  # fmt: skip

_COLOR = re.compile(
    r"^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|[a-zA-Z]{3,20}"
    r"|(rgb|rgba|hsl|hsla)\([0-9.,%\s]{1,40}\))$"
)


def color(v, where="color"):
    """Validate a CSS color. Colors are written into SVG attributes, so anything else is refused."""
    if not isinstance(v, str) or not _COLOR.match(v.strip()):
        raise SpecError(f'{where}: {v!r} is not a color; use "#rrggbb", a CSS name or rgb(...)')
    return v.strip()


# ---------------------------------------------------------------- helpers

_NARROW = set("il.,:;|!'`")
_SEMI = set('fjtrI()[]{}/\\- "')
_WIDE = set("mwMW@%")


def text_w(s, size=12):
    """Approximate rendered width of s in a sans-serif font (no font files needed)."""
    w = 0.0
    for ch in str(s):
        if ch in _NARROW:
            w += 0.28
        elif ch in _SEMI:
            w += 0.35
        elif ch in _WIDE:
            w += 0.86
        elif ord(ch) > 0x2E80:
            w += 1.0
        elif ch.isupper():
            w += 0.68
        elif ch.isdigit():
            w += 0.56
        else:
            w += 0.53
    return w * size


def fit(s, size, maxw):
    """Truncate s with an ellipsis so it fits maxw pixels."""
    s = str(s)[:MAX_TEXT]
    if text_w(s, size) <= maxw:
        return s
    # Binary search on the cut point: linear trimming is quadratic on long labels.
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_w(s[:mid] + "\u2026", size) <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + "\u2026"


def n(x):
    """Compact number for SVG attributes."""
    s = f"{x:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


def _nice(x, rnd):
    e = math.floor(math.log10(x))
    f = x / 10**e
    if rnd:
        m = 1 if f < 1.5 else 2 if f < 3 else 5 if f < 7 else 10
    else:
        m = 1 if f <= 1 else 2 if f <= 2 else 5 if f <= 5 else 10
    return m * 10**e


def ticks(lo, hi, count=5):
    """Nice, round tick values covering [lo, hi]. Returns (ticks, step)."""
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo <= 1e-9 * max(1.0, abs(lo), abs(hi)):
        hi = lo
    if hi == lo:
        if lo == 0:
            hi = 1
        else:
            d = abs(lo) * 0.5
            lo, hi = lo - d, hi + d
    step = _nice(_nice(hi - lo, False) / max(1, count - 1), True)
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step
    k = max(1, int(round((end - start) / step)))
    return [round(start + i * step, 10) for i in range(k + 1)], step


def _decimals(step):
    for d in range(7):
        if abs(round(step, d) - step) < 1e-9 * max(1.0, abs(step)):
            return d
    return 6


def fmt(v, step=None, pre="", suf="", compact=True, dec=None):
    """Format a number for a label: 1500 -> 1.5K, prefix/suffix applied after the sign.
    `dec` forces a fixed number of decimals (zeros kept)."""
    if v is None:
        return ""
    if dec is not None:
        a = abs(v)
        div, unit = 1, ""
        if compact:
            for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
                if a >= d:
                    div, unit = d, u
                    break
        s = f"{a / div:,.{dec}f}"
        sign = "-" if v < 0 and s.strip("0.,") else ""
        return f"{sign}{pre}{s}{unit}{suf}"
    a = abs(v)
    div, unit = 1, ""
    if compact:
        for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if a >= d:
                div, unit = d, u
                break
    x = abs(v) / div
    if step is not None:
        dec = _decimals(step / div)
    else:
        dec = 0 if x >= 100 else 1 if x >= 10 else 2
    s = f"{x:,.{dec}f}" if div == 1 else f"{x:.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    sign = "-" if v < 0 and s.strip("0.,") else ""
    return f"{sign}{pre}{s}{unit}{suf}"


def _lum(c):
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = (int(c[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 0.0
    f = lambda u: u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def on(color):
    """Readable text color on top of a fill color."""
    return "#111827" if _lum(color) > 0.4 else "#ffffff"


def _num(v, where):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise SpecError(f"{where}: expected a number, got {v!r}")
    if abs(v) > MAX_ABS:
        raise SpecError(f"{where}: {v!r} is too large (max {MAX_ABS:g}); scale the data first")
    return float(v)


def opt_num(s, key, default=None, lo=None, hi=None, integer=False):
    """Read a numeric option, with a clear error when it is missing a bound or the wrong type."""
    v = s.get(key)
    if v is None:
        v = default
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise SpecError(f'"{key}" must be a number, got {v!r}')
    if integer:
        v = int(v)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise SpecError(f'"{key}" must be {lo}..{hi}, got {v!r}')
    return v


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- canvas


class Canvas:
    def __init__(self, spec):
        self.s = spec
        theme = spec.get("theme", "light")
        if theme not in THEMES:
            raise SpecError(f'theme must be "light" or "dark", got {theme!r}')
        self.th = THEMES[theme]
        pal = spec.get("palette", "default")
        if pal == "default":
            self.pal = PALETTES[theme]
        elif pal in NAMED_PALETTES:
            self.pal = NAMED_PALETTES[pal]
        else:
            raise SpecError(f'"palette" must be one of: default, {", ".join(NAMED_PALETTES)}')
        spark = spec.get("type") == "sparkline"
        self.W = opt_num(spec, "w", spec.get("width", 120 if spark else 640), 40 if spark else 160, 4000, True)
        self.H = opt_num(spec, "h", spec.get("height", 32 if spark else 400), 16 if spark else 120, 4000, True)
        self.fullH = self.H
        self.out = []
        self.pre = str(spec.get("prefix", ""))[:12]
        self.suf = str(spec.get("suffix", ""))[:12]
        self.compact = spec.get("compact", True)
        if self.suf[:1] in ("K", "M", "B", "T", "k", "m", "b"):
            self.compact = False  # values are already scaled: "$1,240K", not "$1.24KK"
        self.dec = opt_num(spec, "decimals", None, 0, 6, True)
        self.grid = spec.get("grid", True) is not False
        self.legend_at = spec.get("legend", "top")
        if self.legend_at not in ("top", "bottom", "none"):
            raise SpecError('"legend" must be "top", "bottom" or "none"')
        self.bottom_legend = None
        font = spec.get("font")
        if font is not None and (not isinstance(font, str) or not re.match(r"^[\w\s,'.-]{1,120}$", font)):
            raise SpecError('"font" must be a CSS font-family list, like "Inter, sans-serif"')
        self.font = font or FONT
        bg = spec.get("bg", self.th["bg"] if not spark else "none")
        self.bg = bg if bg == "none" else color(bg, '"bg"')

    def f(self, v, step=None):
        return fmt(v, None if self.dec is not None else step, self.pre, self.suf, self.compact, self.dec)

    def add(self, x):
        self.out.append(x)

    def text(self, x, y, t, size=12, fill=None, anchor=None, weight=None, rotate=None):
        a = f'<text x="{n(x)}" y="{n(y)}"'
        if size != 12:
            a += f' font-size="{size}"'
        if fill and fill != self.th["fg"]:
            a += f' fill="{fill}"'
        if anchor:
            a += f' text-anchor="{anchor}"'
        if weight:
            a += f' font-weight="{weight}"'
        if rotate:
            a += f' transform="rotate({rotate} {n(x)} {n(y)})"'
        self.add(f"{a}>{escape(str(t))}</text>")

    def line(self, x1, y1, x2, y2, stroke, w=1):
        if y1 == y2 and w == 1:
            y1 = y2 = math.floor(y1) + 0.5
        if x1 == x2 and w == 1:
            x1 = x2 = math.floor(x1) + 0.5
        self.add(
            f'<path d="M{n(x1)} {n(y1)}L{n(x2)} {n(y2)}" stroke="{stroke}"'
            + (f' stroke-width="{w}"' if w != 1 else "")
            + "/>"
        )

    def rect(self, x, y, w, h, fill, extra=""):
        self.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" fill="{fill}"{extra}/>')

    def bar(self, x, y, w, h, fill, horizontal=False, r=3):
        """Bar from (x, y) with size (w, h), rounding the end away from the baseline.
        For vertical bars h<0 grows downward; for horizontal bars w<0 grows left."""
        if horizontal:
            L = abs(w)
            if L < 0.5:
                return
            r = min(r, h / 2, L)
            x0, x1 = x, x + w
            k = 1 if w > 0 else -1
            d = (
                f"M{n(x0)} {n(y)}H{n(x1 - k * r)}Q{n(x1)} {n(y)} {n(x1)} {n(y + r)}"
                f"V{n(y + h - r)}Q{n(x1)} {n(y + h)} {n(x1 - k * r)} {n(y + h)}H{n(x0)}Z"
            )
        else:
            L = abs(h)
            if L < 0.5:
                return
            r = min(r, w / 2, L)
            y0, y1 = y, y - h
            k = 1 if h > 0 else -1
            d = (
                f"M{n(x)} {n(y0)}V{n(y1 + k * r)}Q{n(x)} {n(y1)} {n(x + r)} {n(y1)}"
                f"H{n(x + w - r)}Q{n(x + w)} {n(y1)} {n(x + w)} {n(y1 + k * r)}V{n(y0)}Z"
            )
        self.add(f'<path d="{d}" fill="{fill}"/>')

    def colors(self, names):
        c = self.s.get("colors")
        if isinstance(c, dict):
            return [
                color(c[nm], f"colors.{nm}") if nm in c else self.pal[i % len(self.pal)] for i, nm in enumerate(names)
            ]
        if isinstance(c, list) and c:
            c = [color(x, "colors") for x in c[:50]]
            return [c[i % len(c)] for i in range(len(names))]
        if c is not None and not isinstance(c, (dict, list)):
            raise SpecError('"colors" must be a list of colors or an object {series: color}')
        return [self.pal[i % len(self.pal)] for i in range(len(names))]

    def place_legend(self, items, top):
        """Draw the series legend where the spec asks. Returns the new top of the plot area."""
        if not items or self.legend_at == "none":
            return top
        if self.legend_at == "bottom":
            lh = self.legend(items, 0, draw=False) - 8
            self.H -= lh
            self.bottom_legend = items
            return top
        return self.legend(items, top)

    def header(self):
        y = 14
        title, sub = self.s.get("title"), self.s.get("subtitle")
        if title:
            self.text(16, y + 16, fit(title, 16, self.W - 32), 16, weight=600)
            y += 24
        if sub:
            self.text(16, y + 13, fit(sub, 12, self.W - 32), 12, self.th["muted"])
            y += 19
        return y + (10 if title or sub else 4)

    def legend(self, items, y, x0=16, maxw=None, draw=True):
        """Flowing legend row(s). Returns the y below it."""
        if not items:
            return y
        maxw = maxw or self.W - 32
        x = x0
        for label, col in items:
            label = fit(label, 12, maxw - 14)
            w = 14 + text_w(label, 12) + 16
            if x + w > x0 + maxw + 16 and x > x0:
                x, y = x0, y + 18
            if draw:
                self.rect(x, y + 1, 10, 10, col, ' rx="2"')
                self.text(x + 14, y + 10, label, 12)
            x += w
        return y + 26

    def svg(self):
        th = self.th
        title = self.s.get("title")
        if self.bottom_legend:
            self.legend(self.bottom_legend, self.H + 2)
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.W}" height="{self.fullH}" '
            f'viewBox="0 0 {self.W} {self.fullH}" font-family="{escape(self.font, quote=False)}" font-size="12" '
            f'fill="{th["fg"]}" role="img"' + (f' aria-label="{escape(str(title)[:MAX_TEXT])}"' if title else "") + ">"
        )
        parts = [head]
        if title:
            parts.append(f"<title>{escape(str(title)[:MAX_TEXT])}</title>")
        if self.bg != "none":
            parts.append(f'<rect width="100%" height="100%" fill="{self.bg}"/>')
        parts.extend(self.out)
        parts.append("</svg>")
        return "".join(parts)


# ---------------------------------------------------------------- data


def cat_series(s):
    """Normalise categorical data to (labels, {name: [values]})."""
    data, x, ser = s.get("data"), s.get("x"), s.get("series")
    if ser is None:
        if isinstance(data, dict):
            x, ser = list(data), {"": list(data.values())}
        elif isinstance(data, list) and data and isinstance(data[0], (list, tuple)):
            x, ser = [p[0] for p in data], {"": [p[1] for p in data]}
        elif isinstance(data, list):
            ser = {"": data}
        else:
            raise SpecError('give "data": {label: value} or "x": [...] with "series": {name: [values]}')
    elif isinstance(ser, list):
        ser = {"": ser}
    elif not isinstance(ser, dict) or not ser:
        raise SpecError('"series" must be an object {name: [values]}')
    # series given as {name: {label: value}}
    if all(isinstance(v, dict) for v in ser.values()):
        keys = list(x) if x else []
        for v in ser.values():
            keys += [k for k in v if k not in keys]
        x = keys
        ser = {nm: [v.get(k) for k in x] for nm, v in ser.items()}
    if any(not isinstance(v, list) for v in ser.values()):
        raise SpecError("every series must be a list of values")
    lens = {len(v) for v in ser.values()}
    if len(lens) != 1:
        raise SpecError("every series must have the same length")
    if x is None:
        x = [str(i + 1) for i in range(lens.pop())]
    if len(x) != len(next(iter(ser.values()))):
        raise SpecError(f'"x" has {len(x)} labels but series have {len(next(iter(ser.values())))} values')
    if not x:
        raise SpecError("no data")
    if len(x) * len(ser) > MAX_POINTS:
        raise SpecError(f"too many values (max {MAX_POINTS}); aggregate the data first")
    out = {}
    for nm, vals in ser.items():
        out[str(nm)] = [_num(v, f"series {nm!r}") for v in vals]
    return x, out


def _named(names):
    return len(names) > 1 or bool(names[0])


# ---------------------------------------------------------------- cartesian frame


def parse_refs(s):
    """Reference lines: "refs": [{"value": 100, "label": "Target"}] or [100]."""
    refs = s.get("refs")
    if refs is None:
        return []
    if not isinstance(refs, list) or len(refs) > 10:
        raise SpecError('"refs" must be a list of up to 10 items like {"value": 100, "label": "Target"}')
    out = []
    for r in refs:
        if _isnum(r):
            r = {"value": r}
        if not isinstance(r, dict):
            raise SpecError('each ref must be a number or {"value": 100, "label": "Target"}')
        v = _num(r.get("value", r.get("y", r.get("x"))), "refs.value")
        if v is None:
            raise SpecError('each ref needs a "value"')
        out.append((v, str(r.get("label", ""))[:60]))
    return out


class Plot:
    """Axes with a linear y scale and a categorical ("cat") or linear ("lin") x scale."""

    def __init__(self, c, top, ylo, yhi, xspec, thin=False, vgrid=False):
        s, th = c.s, c.th
        self.c = c
        self.refs = parse_refs(s)
        for v, _ in self.refs:
            ylo, yhi = min(ylo, v), max(yhi, v)
        ymin, ymax = opt_num(s, "ymin"), opt_num(s, "ymax")
        if ymin is not None:
            ylo = ymin
        if ymax is not None:
            yhi = ymax
        if ylo > yhi:
            raise SpecError('"ymin" must be below "ymax"')
        est = max(80, c.H - top - 50)
        self.yt, ystep = ticks(ylo, yhi, max(3, min(8, round(est / 60) + 1)))
        ylab = [c.f(v, ystep) for v in self.yt]
        left = 16 + max(text_w(t, 11) for t in ylab) + 8 + (20 if s.get("ylabel") else 0)
        right = 16
        self.kind = xspec[0]
        rot, every = False, 1
        if self.kind == "lin":
            pw0 = c.W - left - right
            self.xt, xstep = ticks(xspec[1], xspec[2], max(3, min(10, int(pw0 // 90))))
            big = max(abs(self.xt[0]), abs(self.xt[-1])) >= 10000
            xlab = [fmt(v, xstep, compact=c.compact and big) for v in self.xt]
            right = max(right, text_w(xlab[-1], 11) / 2 + 4)
            left = max(left, text_w(xlab[0], 11) / 2 + 4)
            xlh = 18
        else:
            labels = [str(v) for v in xspec[1]]
            nn = len(labels)
            band = (c.W - left - right) / nn
            mw = max(text_w(t, 11) for t in labels)
            if mw <= band - 6:
                xlh = 18
            elif thin or nn > 24:
                every = math.ceil((min(mw, 120) + 12) / band)
                labels = [fit(t, 11, band * every - 10) for t in labels]
                xlh = 18
            else:
                rot = True
                cap = min(150.0, c.H * 0.3 / 0.643)
                labels = [fit(t, 11, cap) for t in labels]
                mw = min(mw, cap)
                xlh = mw * 0.643 + 18
                left = max(left, mw * 0.766 - band / 2 + 12)
            xlab = labels
        bottom = 8 + xlh + (20 if s.get("xlabel") else 0)
        self.L, self.T, self.R, self.B = left, top, c.W - right, c.H - bottom
        self.W, self.H = self.R - self.L, self.B - self.T
        if self.H < 40 or self.W < 60:
            raise SpecError("not enough room for the plot; increase w/h or shorten labels")
        self.y0, self.y1 = self.yt[0], self.yt[-1]
        for v, t in zip(self.yt, ylab):
            yy = self.y(v)
            if c.grid:
                c.line(self.L, yy, self.R, yy, th["grid"])
            c.text(self.L - 8, yy + 4, t, 11, th["muted"], "end")
        if self.kind == "lin":
            self.x0, self.x1 = self.xt[0], self.xt[-1]
            for v, t in zip(self.xt, xlab):
                xx = self.x(v)
                if vgrid and c.grid:
                    c.line(xx, self.T, xx, self.B, th["grid"])
                c.text(xx, self.B + 17, t, 11, th["muted"], "middle")
        else:
            self.n = len(xlab)
            for i, t in enumerate(xlab):
                if i % every:
                    continue
                bx, bw = self.band(i)
                cx = bx + bw / 2
                if rot:
                    c.text(cx + 3, self.B + 13, t, 11, th["muted"], "end", rotate=-40)
                else:
                    c.text(cx, self.B + 17, t, 11, th["muted"], "middle")
        if s.get("xlabel"):
            c.text((self.L + self.R) / 2, c.H - 12, fit(s["xlabel"], 12, self.W), 12, th["muted"], "middle")
        if s.get("ylabel"):
            c.text(26, (self.T + self.B) / 2, fit(s["ylabel"], 12, self.H), 12, th["muted"], "middle", rotate=-90)

    def y(self, v):
        y = self.B - (v - self.y0) / (self.y1 - self.y0) * self.H
        return min(self.B, max(self.T, y))  # values outside ymin/ymax are clipped to the frame

    def x(self, v):
        return self.L + (v - self.x0) / (self.x1 - self.x0) * self.W

    def band(self, i):
        bw = self.W / self.n
        return self.L + i * bw, bw

    def finish(self, zero=True):
        c = self.c
        for v, label in self.refs:
            yy = self.y(v)
            c.add(
                f'<path d="M{n(self.L)} {n(yy)}H{n(self.R)}" stroke="{c.th["fg"]}" stroke-opacity=".6" '
                'stroke-dasharray="4 3"/>'
            )
            if label:
                c.text(self.R, yy - 5, fit(label, 11, self.W / 2), 11, c.th["fg"], "end", 500)
        zy = self.y(0) if zero and self.y0 <= 0 <= self.y1 else self.B
        c.line(self.L, zy, self.R, zy, c.th["axis"])


# ---------------------------------------------------------------- chart types


def _sort(s, cats, ser):
    order = s.get("sort")
    if not order:
        return cats, ser
    if order not in ("asc", "desc"):
        raise SpecError('"sort" must be "asc" or "desc"')
    tot = [sum(v[i] or 0 for v in ser.values()) for i in range(len(cats))]
    idx = sorted(range(len(cats)), key=lambda i: tot[i], reverse=order == "desc")
    return [cats[i] for i in idx], {k: [v[i] for i in idx] for k, v in ser.items()}


def _percent(cats, ser):
    """Turn each category's values into shares of 100."""
    out = {k: list(v) for k, v in ser.items()}
    for i in range(len(cats)):
        tot = sum(abs(v[i] or 0) for v in ser.values())
        for k in out:
            out[k][i] = None if ser[k][i] is None else (100 * ser[k][i] / tot if tot else 0.0)
    return out


def _highlight(c, s, cats, base):
    """Per-category colors: highlighted categories keep the series color, the rest are dimmed."""
    h = s.get("highlight")
    if h is None:
        return [base] * len(cats)
    hs = {str(x) for x in (h if isinstance(h, list) else [h])}
    return [base if str(k) in hs else c.th["dim"] for k in cats]


def bar(c, s):
    cats, ser = _sort(s, *cat_series(s))
    names = list(ser)
    cols = c.colors(names)
    stack = bool(s.get("stack")) and len(names) > 1
    if stack and s.get("stack") == "percent":
        ser = _percent(cats, ser)
        c.pre, c.suf = "", "%"
    ng = 1 if stack else len(names)
    cat_cols = _highlight(c, s, cats, cols[0]) if ng == 1 else None
    horiz = s.get("type") == "hbar" or bool(s.get("horizontal"))
    if horiz and "h" not in s and "height" not in s:
        top0 = c.header()
        c.out.clear()
        per = 26 if ng == 1 else ng * 13 + 12
        c.H = int(max(200, top0 + (26 if _named(names) else 0) + len(cats) * per + 44 + (20 if s.get("xlabel") else 0)))
        c.H = min(c.H, 4000)
        c.fullH = c.H
    top = c.header()
    if _named(names):
        top = c.place_legend(list(zip(names, cols)), top)
    if stack:
        pos = [sum(max(0, v[i] or 0) for v in ser.values()) for i in range(len(cats))]
        neg = [sum(min(0, v[i] or 0) for v in ser.values()) for i in range(len(cats))]
        lo, hi = min(0, min(neg)), max(0, max(pos))
    else:
        vals = [v for vs in ser.values() for v in vs if v is not None] or [0]
        lo, hi = min(0, min(vals)), max(0, max(vals))
    labels = s.get("labels", (ng == 1 and len(cats) <= 16) or (stack and len(cats) <= 16))
    if stack and s.get("stack") == "percent":
        lo, hi = 0, 100
    if horiz:
        return _hbar(c, s, cats, ser, names, cols, stack, ng, lo, hi, top, labels, cat_cols)
    if labels and not (stack and s.get("stack") == "percent"):
        hi, lo = hi + (hi - lo) * 0.07 * (hi > 0), lo - (hi - lo) * 0.07 * (lo < 0)
    p = Plot(c, top, lo, hi, ("cat", cats))
    bg = c.th["bg"]
    for i in range(len(cats)):
        x0, bw = p.band(i)
        pad = bw * (0.18 if ng == 1 else 0.12)
        gx, gw = x0 + pad, bw - 2 * pad
        if stack:
            pa = na = 0.0
            for j, nm in enumerate(names):
                v = ser[nm][i]
                if not v:
                    continue
                a, b = (pa, pa + v) if v > 0 else (na, na + v)
                if v > 0:
                    pa = b
                else:
                    na = b
                ya, yb = p.y(a), p.y(b)
                c.rect(gx, min(ya, yb), gw, abs(ya - yb), cols[j], f' stroke="{bg}" stroke-width="1"')
            if labels and pa and s.get("stack") != "percent":
                t = c.f(pa)
                if text_w(t, 11) <= bw:
                    c.text(gx + gw / 2, p.y(pa) - 5, t, 11, anchor="middle")
        else:
            inner = gw / ng
            gap = min(3, inner * 0.12) if ng > 1 else 0
            for j, nm in enumerate(names):
                v = ser[nm][i]
                if v is None:
                    continue
                bx, bwj = gx + j * inner + gap / 2, inner - gap
                c.bar(bx, p.y(0), bwj, p.y(0) - p.y(v), cat_cols[i] if cat_cols else cols[j])
                if labels:
                    t = c.f(v)
                    if text_w(t, 11) <= inner + 6:
                        c.text(bx + bwj / 2, p.y(v) - 5 if v >= 0 else p.y(v) + 14, t, 11, anchor="middle")
    p.finish()


def _hbar(c, s, cats, ser, names, cols, stack, ng, lo, hi, top, labels, cat_cols=None):
    th = c.th
    labw = min(max(text_w(t, 11) for t in cats), c.W * 0.35)
    left = 16 + labw + 10
    vlab = 0
    if labels:
        tot = (
            [sum(max(0, v[i] or 0) for v in ser.values()) for i in range(len(cats))]
            if stack
            else [v for vs in ser.values() for v in vs if v is not None]
        )
        vlab = max(text_w(c.f(v), 11) for v in tot) + 8
    right = 16 + vlab
    bottom = 30 + (20 if s.get("xlabel") else 0)
    refs = parse_refs(s)
    for v, _ in refs:
        lo, hi = min(lo, v), max(hi, v)
    lo = opt_num(s, "ymin", lo)
    hi = opt_num(s, "ymax", hi)
    if lo > hi:
        raise SpecError('"ymin" must be below "ymax"')
    L, R, T, B = left, c.W - right, top, c.H - bottom
    if R - L < 60 or B - T < 40:
        raise SpecError("not enough room for the plot; increase w/h or shorten labels")
    xt, step = ticks(lo, hi, max(3, min(8, int((R - L) // 80))))
    x0, x1 = xt[0], xt[-1]
    X = lambda v: L + (v - x0) / (x1 - x0) * (R - L)  # noqa: E731
    for v in xt:
        if c.grid:
            c.line(X(v), T, X(v), B, th["grid"])
        c.text(X(v), B + 17, c.f(v, step), 11, th["muted"], "middle")
    bh = (B - T) / len(cats)
    bg = th["bg"]
    for i, cat in enumerate(cats):
        y0 = T + i * bh
        c.text(L - 10, y0 + bh / 2 + 4, fit(cat, 11, labw), 11, anchor="end")
        pad = bh * (0.18 if ng == 1 else 0.12)
        gy, gh = y0 + pad, bh - 2 * pad
        if stack:
            pa = na = 0.0
            for j, nm in enumerate(names):
                v = ser[nm][i]
                if not v:
                    continue
                a, b = (pa, pa + v) if v > 0 else (na, na + v)
                if v > 0:
                    pa = b
                else:
                    na = b
                c.rect(min(X(a), X(b)), gy, abs(X(b) - X(a)), gh, cols[j], f' stroke="{bg}" stroke-width="1"')
            if labels and pa and s.get("stack") != "percent":
                c.text(X(pa) + 5, gy + gh / 2 + 4, c.f(pa), 11)
        else:
            inner = gh / ng
            gap = min(3, inner * 0.12) if ng > 1 else 0
            for j, nm in enumerate(names):
                v = ser[nm][i]
                if v is None:
                    continue
                by, bhj = gy + j * inner + gap / 2, inner - gap
                c.bar(X(0), by, X(v) - X(0), bhj, cat_cols[i] if cat_cols else cols[j], horizontal=True)
                if labels and bhj >= 9:
                    c.text(X(v) + (5 if v >= 0 else -5), by + bhj / 2 + 4, c.f(v), 11, anchor=None if v >= 0 else "end")
    for v, label in refs:
        c.add(f'<path d="M{n(X(v))} {n(T)}V{n(B)}" stroke="{th["fg"]}" stroke-opacity=".6" stroke-dasharray="4 3"/>')
        if label:
            c.text(X(v) + 4, T + 10, fit(label, 11, (R - L) / 2), 11, th["fg"], None, 500)
    zx = X(0) if x0 <= 0 <= x1 else L
    c.line(zx, T, zx, B, th["axis"])
    if s.get("xlabel"):
        c.text((L + R) / 2, c.H - 12, fit(s["xlabel"], 12, R - L), 12, th["muted"], "middle")


def _segments(pts):
    segs, cur = [], []
    for p in pts:
        if p[1] is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(p)
    if cur:
        segs.append(cur)
    return segs


def _pathd(pts):
    return "M" + "L".join(f"{n(x)} {n(y)}" for x, y in pts)


def _curve(pts, mode="linear", move=True):
    """Path through pts. "smooth" is monotone cubic, so it never overshoots the data."""
    head = ("M" if move else "L") + f"{n(pts[0][0])} {n(pts[0][1])}"
    if len(pts) < 2 or mode == "linear":
        return head + "".join(f"L{n(x)} {n(y)}" for x, y in pts[1:])
    if mode == "step":
        out = head
        for (_, y0), (x1, y1) in zip(pts, pts[1:]):
            out += f"H{n(x1)}" + (f"V{n(y1)}" if y1 != y0 else "")
        return out
    k = len(pts)
    d = [(pts[i + 1][1] - pts[i][1]) / ((pts[i + 1][0] - pts[i][0]) or 1e-9) for i in range(k - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, k - 1)] + [d[-1]]
    for i in range(k - 1):  # Fritsch-Carlson limits keep the curve monotone between points
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        h = a * a + b * b
        if h > 9:
            t = 3 / math.sqrt(h)
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    out = head
    for i in range(k - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        dx = (x1 - x0) / 3
        out += f"C{n(x0 + dx)} {n(y0 + m[i] * dx)} {n(x1 - dx)} {n(y1 - m[i + 1] * dx)} {n(x1)} {n(y1)}"
    return out


def line(c, s, area=False):
    raw_x = s.get("x")
    numeric = bool(raw_x) and all(_isnum(v) for v in raw_x)
    if numeric and len(raw_x) <= 40 and all(float(v).is_integer() and 1000 <= v <= 2999 for v in raw_x):
        numeric = False  # years: one tick per year, never "2.02K"
        s = dict(s, x=[str(int(v)) for v in raw_x])
    cats, ser = cat_series(s)
    idx = list(range(len(cats)))
    if numeric:
        idx.sort(key=lambda i: raw_x[i])
    names = list(ser)
    cols = c.colors(names)
    stack = area and bool(s.get("stack")) and len(names) > 1
    if stack and s.get("stack") == "percent":
        ser = _percent(cats, ser)
        c.pre, c.suf = "", "%"
    mode = s.get("curve", "linear")
    if mode not in ("linear", "smooth", "step"):
        raise SpecError('"curve" must be "linear", "smooth" or "step"')
    top = c.header()
    if _named(names):
        top = c.place_legend(list(zip(names, cols)), top)
    series = [[ser[nm][i] for i in idx] for nm in names]
    if stack:
        acc, cum = [0.0] * len(idx), []
        for vs in series:
            acc = [a + (v or 0) for a, v in zip(acc, vs)]
            cum.append(acc)
        vals = [v for vs in cum for v in vs]
    else:
        vals = [v for vs in series for v in vs if v is not None]
    if not vals:
        raise SpecError("no numeric values")
    lo, hi = min(vals), max(vals)
    if area or s.get("zero"):
        lo, hi = min(0, lo), max(0, hi)
    if stack and s.get("stack") == "percent":
        lo, hi = 0, 100
    if s.get("labels"):
        hi += (hi - lo) * 0.07
    if numeric:
        p = Plot(c, top, lo, hi, ("lin", min(raw_x), max(raw_x)))
        xs = [p.x(raw_x[i]) for i in idx]
    else:
        p = Plot(c, top, lo, hi, ("cat", cats), thin=True)
        xs = [p.band(i)[0] + p.band(i)[1] / 2 for i in idx]
    base = p.y(max(p.y0, min(0, p.y1)))
    bg = c.th["bg"]
    one = len(names) == 1
    for j, vs in enumerate(series):
        col = cols[j]
        if stack:
            up = list(zip(xs, [p.y(v) for v in cum[j]]))
            dn = list(zip(xs, [p.y(v) for v in cum[j - 1]] if j else [base] * len(xs)))[::-1]
            c.add(f'<path d="{_curve(up, mode)}{_curve(dn, mode, False)}Z" fill="{col}" fill-opacity=".85"/>')
            c.add(f'<path d="{_curve(up, mode)}" fill="none" stroke="{col}" stroke-width="1.5"/>')
            continue
        pts = [(x, None if v is None else p.y(v)) for x, v in zip(xs, vs)]
        for seg in _segments(pts):
            if area:
                d = _curve(seg, mode) + f"L{n(seg[-1][0])} {n(base)}L{n(seg[0][0])} {n(base)}Z"
                c.add(f'<path d="{d}" fill="{col}" fill-opacity="{".22" if one else ".14"}"/>')
            c.add(
                f'<path d="{_curve(seg, mode)}" fill="none" stroke="{col}" stroke-width="2.25" '
                'stroke-linejoin="round" stroke-linecap="round"/>'
            )
        show_dots = s.get("dots", len(xs) <= 24)
        for (x, y), v in zip(pts, vs):
            if y is None:
                continue
            if show_dots:
                c.add(f'<circle cx="{n(x)}" cy="{n(y)}" r="3" fill="{col}" stroke="{bg}" stroke-width="1.5"/>')
            if s.get("labels"):
                c.text(x, y - 8, c.f(v), 11, anchor="middle")
    p.finish(zero=area or bool(s.get("zero")))


def scatter(c, s):
    ser = s.get("series")
    if ser is None:
        ser = {"": s.get("data")}
    if not isinstance(ser, dict):
        raise SpecError('scatter needs "data": [[x, y], ...] or "series": {name: [[x, y], ...]}')
    pts = {}
    if sum(len(v) for v in ser.values() if isinstance(v, list)) > MAX_POINTS:
        raise SpecError(f"too many points (max {MAX_POINTS}); sample the data first")
    for nm, ps in ser.items():
        if not isinstance(ps, list) or not ps:
            raise SpecError(f"series {nm!r}: expected a list of [x, y] points")
        out = []
        for p in ps:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                raise SpecError(f"series {nm!r}: each point must be [x, y], [x, y, size] or [x, y, label]")
            size = _num(p[2], f"series {nm!r} size") if len(p) > 2 and _isnum(p[2]) else None
            if size is not None and size < 0:
                raise SpecError(f"series {nm!r}: point sizes must be >= 0")
            lab = next((str(q)[:MAX_TEXT] for q in p[2:] if isinstance(q, str)), None)
            px, py = _num(p[0], nm), _num(p[1], nm)
            if px is None or py is None:
                raise SpecError(f"series {nm!r}: x and y must be numbers, not null")
            out.append((px, py, size, lab))
        pts[str(nm)] = out
    names = list(pts)
    cols = c.colors(names)
    top = c.header()
    if _named(names):
        top = c.place_legend(list(zip(names, cols)), top)
    allp = [p for ps in pts.values() for p in ps]
    xs, ys = [p[0] for p in allp], [p[1] for p in allp]
    pad = lambda a, b: (b - a) * 0.04 or 1  # noqa: E731
    px, py = pad(min(xs), max(xs)), pad(min(ys), max(ys))
    p = Plot(c, top, min(ys) - py, max(ys) + py, ("lin", min(xs) - px, max(xs) + px), vgrid=True)
    smax = max((q[2] for q in allp if q[2]), default=0)
    bg = c.th["bg"]
    for j, nm in enumerate(names):
        for x, y, size, lab in pts[nm]:
            r = 3 + 13 * math.sqrt(size / smax) if size and smax > 0 else 4.5
            c.add(
                f'<circle cx="{n(p.x(x))}" cy="{n(p.y(y))}" r="{n(r)}" fill="{cols[j]}" '
                f'fill-opacity=".75" stroke="{bg}" stroke-width=".75"/>'
            )
            if lab:
                c.text(p.x(x) + r + 3, p.y(y) + 4, fit(lab, 11, 140), 11)
    p.finish(zero=False)


def histogram(c, s):
    vals = s.get("values", s.get("data"))
    if not isinstance(vals, list) or not vals:
        raise SpecError('histogram needs "values": [numbers]')
    if len(vals) > 100 * MAX_POINTS:
        raise SpecError(f"too many values (max {100 * MAX_POINTS})")
    vals = [_num(v, "values") for v in vals if v is not None]
    if not vals:
        raise SpecError("histogram needs at least one number")
    nb = opt_num(s, "bins", math.ceil(math.log2(len(vals)) + 1), 1, 200, True)
    lo, hi = min(vals), max(vals)
    if hi - lo <= 1e-9 * max(1.0, abs(lo)):
        hi = lo + 1
    step = _nice((hi - lo) / max(1, nb), True)
    start = math.floor(lo / step) * step
    edges = [start]
    while edges[-1] <= hi:
        edges.append(round(edges[-1] + step, 10))
    counts = [0] * (len(edges) - 1)
    for v in vals:
        counts[min(int((v - start) // step), len(counts) - 1)] += 1
    col = c.colors([""])[0]
    top = c.header()
    p = Plot(c, top, 0, max(counts), ("lin", edges[0], edges[-1]))
    for i, k in enumerate(counts):
        if not k:
            continue
        xa, xb = p.x(edges[i]), p.x(edges[i + 1])
        c.rect(xa + 0.5, p.y(k), max(0.5, xb - xa - 1), p.y(0) - p.y(k), col)
    p.finish()


def _pct(share):
    v = share * 100
    if 0 < v < 1:
        return "<1%"
    return (f"{v:.0f}" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".")) + "%"


def pie(c, s, donut=False):
    cats, ser = cat_series(s)
    if len(ser) != 1:
        raise SpecError("pie/donut takes a single series")
    vals = next(iter(ser.values()))
    items = [(str(k), v) for k, v in zip(cats, vals) if v]
    if any(v < 0 for _, v in items):
        raise SpecError("pie/donut values must be >= 0")
    if not items:
        raise SpecError("pie/donut needs at least one value > 0")
    if s.get("sort", "desc") == "desc":
        items.sort(key=lambda t: -t[1])
    mx = opt_num(s, "max_slices", 8, 2, 50, True)
    if len(items) > mx:
        items = items[: mx - 1] + [("Other", sum(v for _, v in items[mx - 1 :]))]
    total = sum(v for _, v in items)
    cols = c.colors([k for k, _ in items])
    if any(k == "Other" for k, _ in items[-1:]) and len(items) > mx - 1 and not s.get("colors"):
        cols[-1] = c.th["axis"]
    th = c.th
    top = c.header()
    aw, ah = c.W - 32, c.H - top - 16
    leg = [(k, cols[i], _pct(v / total)) for i, (k, v) in enumerate(items)]
    side = aw > ah * 1.3
    if side:
        lw = min(c.W * 0.42, max(text_w(k, 12) + text_w(p, 12) for k, _, p in leg) + 40)
        lh = 22 * len(leg)
        r = min(aw - lw - 24, ah) / 2 - 2
        cx, cy = 16 + (aw - lw - 24) / 2, top + ah / 2
        ly = cy - lh / 2 + 4
        lx = c.W - 16 - lw
        for k, col, pct in leg:
            c.rect(lx, ly + 1, 10, 10, col, ' rx="2"')
            c.text(lx + 16, ly + 10, fit(k, 12, lw - text_w(pct, 12) - 30), 12)
            c.text(c.W - 16, ly + 10, pct, 12, th["muted"], "end")
            ly += 22
    else:
        items_l = [(f"{k}  {p}", col) for k, col, p in leg]
        lh = c.legend(items_l, 0, draw=False)
        r = min(aw, ah - lh) / 2 - 2
        cx, cy = c.W / 2, top + r
        c.legend(items_l, top + 2 * r + 12)
    if r < 20:
        raise SpecError("not enough room for the pie; increase w/h")
    ri = r * opt_num(s, "hole", 0.6, 0.2, 0.9) if donut else 0
    bg = th["bg"]
    a0 = -math.pi / 2
    P = lambda rad, a: (cx + rad * math.cos(a), cy + rad * math.sin(a))  # noqa: E731
    for i, (_, v) in enumerate(items):
        share = v / total
        a1 = a0 + 2 * math.pi * share
        col = cols[i]
        if len(items) == 1:
            if donut:
                c.add(
                    f'<path d="M{n(cx - r)} {n(cy)}a{n(r)} {n(r)} 0 1 0 {n(2 * r)} 0a{n(r)} {n(r)} 0 1 0 {n(-2 * r)} 0Z'
                    f'M{n(cx - ri)} {n(cy)}a{n(ri)} {n(ri)} 0 1 1 {n(2 * ri)} 0a{n(ri)} {n(ri)} 0 1 1 {n(-2 * ri)} 0Z" '
                    f'fill="{col}" fill-rule="evenodd"/>'
                )
            else:
                c.add(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}" fill="{col}"/>')
        else:
            large = 1 if share > 0.5 else 0
            (ox0, oy0), (ox1, oy1) = P(r, a0), P(r, a1)
            if donut:
                (ix0, iy0), (ix1, iy1) = P(ri, a0), P(ri, a1)
                d = (
                    f"M{n(ox0)} {n(oy0)}A{n(r)} {n(r)} 0 {large} 1 {n(ox1)} {n(oy1)}"
                    f"L{n(ix1)} {n(iy1)}A{n(ri)} {n(ri)} 0 {large} 0 {n(ix0)} {n(iy0)}Z"
                )
            else:
                d = f"M{n(cx)} {n(cy)}L{n(ox0)} {n(oy0)}A{n(r)} {n(r)} 0 {large} 1 {n(ox1)} {n(oy1)}Z"
            c.add(f'<path d="{d}" fill="{col}" stroke="{bg}" stroke-width="1.5" stroke-linejoin="round"/>')
        if share >= 0.05 and r >= 60:
            mid = (a0 + a1) / 2
            lr = (r + ri) / 2 if donut else r * 0.64
            tx, ty = P(lr, mid)
            c.text(tx, ty + 4, _pct(share), 11, on(col), "middle", 600)
        a0 = a1
    if donut and ri > 30:
        big = str(s.get("center", c.f(total)))[:40]
        sub = s.get("center_label", "Total" if "center" not in s else "")
        size = max(12, min(28, int(ri * 0.42), int((ri * 1.6) / max(1, text_w(big, 1)))))
        c.text(cx, cy + size * 0.35 - (7 if sub else 0), big, size, anchor="middle", weight=600)
        if sub:
            c.text(cx, cy + size * 0.35 + 9, fit(sub, 11, ri * 1.6), 11, th["muted"], "middle")


# ---------------------------------------------------------------- new chart types


def waterfall(c, s):
    """Running total built from changes. "total": "Net" adds a closing total bar."""
    cats, ser = cat_series(s)
    if len(ser) != 1:
        raise SpecError("waterfall takes a single series of changes")
    vals = [v or 0.0 for v in next(iter(ser.values()))]
    cats = [str(k) for k in cats]
    total_label = s.get("total")
    bars, run = [], 0.0  # (label, start, end, kind)
    for k, v in zip(cats, vals):
        bars.append((k, run, run + v, "up" if v >= 0 else "down"))
        run += v
    if total_label:
        bars.append((str(total_label if isinstance(total_label, str) else "Total")[:40], 0.0, run, "total"))
    ends = [b[1] for b in bars] + [b[2] for b in bars]
    lo, hi = min(0.0, min(ends)), max(0.0, max(ends))
    pad = (hi - lo) * 0.08 or 1
    top = c.header()
    th = c.th
    up, down = c.colors(["up", "down", "total"])[:2] if s.get("colors") else (th["up"], th["down"])
    tot_col = c.colors(["up", "down", "total"])[2] if s.get("colors") else c.pal[0]
    names = {"up": "Increase", "down": "Decrease", "total": "Total"}
    kinds = [k for k in ("up", "down", "total") if any(b[3] == k for b in bars)]
    colmap = {"up": up, "down": down, "total": tot_col}
    if len(kinds) > 1:
        top = c.place_legend([(names[k], colmap[k]) for k in kinds], top)
    p = Plot(c, top, lo - pad * (lo < 0), hi + pad * (hi > 0), ("cat", [b[0] for b in bars]))
    prev = None
    for i, (_, a, b, kind) in enumerate(bars):
        x0, bw = p.band(i)
        pad_x = bw * 0.18
        bx, w = x0 + pad_x, bw - 2 * pad_x
        ya, yb = p.y(a), p.y(b)
        c.rect(bx, min(ya, yb), w, max(1, abs(ya - yb)), colmap[kind], ' rx="2"')
        if prev is not None:
            c.add(f'<path d="M{n(prev)} {n(ya)}H{n(bx)}" stroke="{th["axis"]}" stroke-dasharray="2 2"/>')
        prev = bx + w
        if s.get("labels", len(bars) <= 16):
            delta = b - a
            t = c.f(b) if kind == "total" else ("+" if delta > 0 else "") + c.f(delta)
            if text_w(t, 11) <= bw + 4:
                ty = min(ya, yb) - 5 if (delta >= 0 or kind == "total") else max(ya, yb) + 14
                c.text(bx + w / 2, ty, t, 11, anchor="middle")
    p.finish()


def funnel(c, s):
    """Stages narrowing to the bottom, each with its value and share of the first stage."""
    cats, ser = cat_series(s)
    if len(ser) != 1:
        raise SpecError("funnel takes a single series")
    items = [(str(k), v or 0.0) for k, v in zip(cats, next(iter(ser.values())))]
    if any(v < 0 for _, v in items):
        raise SpecError("funnel values must be >= 0")
    first = items[0][1] or max(v for _, v in items) or 1
    top = c.header()
    th = c.th
    labw = min(max(text_w(k, 12) for k, _ in items) + 12, c.W * 0.3)
    valw = max(text_w(f"{c.f(v)}  100%", 12) for _, v in items) + 12
    L, R = 16 + labw, c.W - 16 - valw
    if R - L < 60:
        raise SpecError("not enough room for the funnel; increase w or shorten labels")
    gap = 4
    hgt = (c.H - top - 12 - gap * (len(items) - 1)) / len(items)
    if hgt < 10:
        raise SpecError("too many stages for this height; increase h")
    mid, full = (L + R) / 2, R - L
    base = c.colors(["stage"])[0]
    peak = max(v for _, v in items) or 1
    for i, (k, v) in enumerate(items):
        y = top + i * (hgt + gap)
        w = max(2.0, full * v / peak)
        nxt = max(2.0, full * items[i + 1][1] / peak) if i + 1 < len(items) else w
        x0, x1 = mid - w / 2, mid + w / 2
        b0, b1 = mid - nxt / 2, mid + nxt / 2
        if s.get("shape") == "bars":
            c.rect(x0, y, w, hgt, base, ' rx="3"')
        else:
            c.add(
                f'<path d="M{n(x0)} {n(y)}H{n(x1)}L{n(b1)} {n(y + hgt)}H{n(b0)}Z" fill="{base}" '
                f'fill-opacity="{n(1 - 0.5 * i / max(1, len(items) - 1))}"/>'
            )
        c.text(L - 12, y + hgt / 2 + 4, fit(k, 12, labw - 8), 12, anchor="end")
        c.text(R + 12, y + hgt / 2 + 4, c.f(v), 12, weight=600)
        c.text(c.W - 16, y + hgt / 2 + 4, _pct(v / first), 12, th["muted"], "end")


def _mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    if len(a) == 3:
        a = "".join(ch * 2 for ch in a)
    if len(b) == 3:
        b = "".join(ch * 2 for ch in b)
    try:
        pa = [int(a[i : i + 2], 16) for i in (0, 2, 4)]
        pb = [int(b[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        raise SpecError('heatmap "colors" must be two hex colors like ["#eef4fb", "#1f4e79"]') from None
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def heatmap(c, s):
    """Rows x columns grid: "x": [columns], "series": {row: [values]}."""
    cols, ser = cat_series(s)
    rows = list(ser)
    vals = [v for vs in ser.values() for v in vs if v is not None]
    if not vals:
        raise SpecError("heatmap needs at least one number")
    lo, hi = min(vals), max(vals)
    th = c.th
    cl = s.get("colors")
    lo_c, hi_c = (color(cl[0]), color(cl[1])) if isinstance(cl, list) and len(cl) >= 2 else (th["lo"], th["hi"])
    top = c.header()
    rowlab = min(max(text_w(r, 11) for r in rows) + 12, c.W * 0.3)
    L, R, T = 16 + rowlab, c.W - 16, top + 4
    B = c.H - 22 - 26
    cw, ch = (R - L) / len(cols), (B - T) / len(rows)
    if cw < 6 or ch < 6:
        raise SpecError("too many cells for this size; increase w/h or aggregate")
    every = max(1, math.ceil((min(max(text_w(str(x), 11) for x in cols), 100) + 8) / cw))
    show = s.get("labels", cw >= 34 and ch >= 18)
    for j, x in enumerate(cols):
        if j % every == 0:
            c.text(L + j * cw + cw / 2, B + 15, fit(str(x), 11, cw * every - 4), 11, th["muted"], "middle")
    for i, r in enumerate(rows):
        c.text(L - 8, T + i * ch + ch / 2 + 4, fit(r, 11, rowlab - 8), 11, anchor="end")
        for j, v in enumerate(ser[r]):
            x0, y0 = L + j * cw, T + i * ch
            if v is None:
                c.rect(x0 + 1, y0 + 1, cw - 2, ch - 2, th["grid"], ' rx="2"')
                continue
            t = (v - lo) / (hi - lo) if hi > lo else 1.0
            fill = _mix(lo_c, hi_c, t)
            c.rect(x0 + 1, y0 + 1, cw - 2, ch - 2, fill, ' rx="2"')
            if show:
                label = c.f(v)
                if text_w(label, 11) <= cw - 4:
                    c.text(x0 + cw / 2, y0 + ch / 2 + 4, label, 11, on(fill), "middle")
    # five-step color key under the grid
    ky = c.H - 20
    kx = L
    c.text(kx, ky + 9, c.f(lo), 11, th["muted"])
    kx += text_w(c.f(lo), 11) + 6
    for k in range(5):
        c.rect(kx + k * 18, ky, 16, 10, _mix(lo_c, hi_c, k / 4), ' rx="2"')
    c.text(kx + 5 * 18 + 4, ky + 9, c.f(hi), 11, th["muted"])


def sparkline(c, s):
    """A tiny line with no axes, for tables and text. Ends with a dot on the last value."""
    cats, ser = cat_series(s)
    vs = next(iter(ser.values()))
    pts_v = [v for v in vs if v is not None]
    if len(pts_v) < 2:
        raise SpecError("sparkline needs at least two numbers")
    lo, hi = min(pts_v), max(pts_v)
    if s.get("zero"):
        lo, hi = min(0, lo), max(0, hi)
    pad = 3
    W, H = c.W, c.H
    span = (hi - lo) or 1
    xs = [pad + i * (W - 2 * pad) / (len(vs) - 1) for i in range(len(vs))]
    pts = [(x, None if v is None else H - pad - (v - lo) / span * (H - 2 * pad)) for x, v in zip(xs, vs)]
    col = c.colors(["s"])[0]
    mode = s.get("curve", "linear")
    if mode not in ("linear", "smooth", "step"):
        raise SpecError('"curve" must be "linear", "smooth" or "step"')
    for seg in _segments(pts):
        if s.get("area"):
            d = _curve(seg, mode) + f"L{n(seg[-1][0])} {n(H - pad)}L{n(seg[0][0])} {n(H - pad)}Z"
            c.add(f'<path d="{d}" fill="{col}" fill-opacity=".18"/>')
        c.add(f'<path d="{_curve(seg, mode)}" fill="none" stroke="{col}" stroke-width="1.5" stroke-linejoin="round"/>')
    last = next((p for p in reversed(pts) if p[1] is not None), None)
    if last and s.get("dot", True):
        c.add(f'<circle cx="{n(last[0])}" cy="{n(last[1])}" r="2" fill="{col}"/>')


# ---------------------------------------------------------------- entry points


def _load(spec):
    if isinstance(spec, (str, bytes)):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as e:
            raise SpecError(f"invalid JSON: {e.msg} at line {e.lineno} col {e.colno}") from None
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    return dict(spec)


def render(spec) -> str:
    """Render a spec (dict or JSON string) to an SVG string."""
    s = _load(spec)
    t = str(s.get("type", "bar")).lower()
    s["type"] = {"column": "bar", "hist": "histogram", "doughnut": "donut"}.get(t, t)
    if s["type"] not in TYPES:
        raise SpecError(f"unknown type {t!r}; use one of: {', '.join(TYPES)}")
    c = Canvas(s)
    t = s["type"]
    if t in ("bar", "hbar"):
        bar(c, s)
    elif t in ("line", "area"):
        line(c, s, area=t == "area")
    elif t == "scatter":
        scatter(c, s)
    elif t == "histogram":
        histogram(c, s)
    elif t == "waterfall":
        waterfall(c, s)
    elif t == "funnel":
        funnel(c, s)
    elif t == "heatmap":
        heatmap(c, s)
    elif t == "sparkline":
        sparkline(c, s)
    else:
        pie(c, s, donut=t == "donut")
    return c.svg()
