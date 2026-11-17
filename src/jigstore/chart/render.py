"""Zero-dependency SVG chart renderer built for agents.

Input is a small dict ("spec"); output is a compact, self-contained SVG string.
"""

from __future__ import annotations

import json
import math
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
THEMES = {
    "light": {"bg": "#ffffff", "fg": "#1f2937", "muted": "#6b7280", "grid": "#e5e7eb", "axis": "#9ca3af"},
    "dark": {"bg": "#0f172a", "fg": "#e2e8f0", "muted": "#94a3b8", "grid": "#1e293b", "axis": "#475569"},
}
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MAX_POINTS = 10000
TYPES = ("bar", "hbar", "line", "area", "scatter", "pie", "donut", "histogram")

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
    s = str(s)
    if text_w(s, size) <= maxw:
        return s
    while s and text_w(s + "\u2026", size) > maxw:
        s = s[:-1]
    return s.rstrip() + "\u2026"


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


def fmt(v, step=None, pre="", suf="", compact=True):
    """Format a number for a label: 1500 -> 1.5K, prefix/suffix applied after the sign."""
    if v is None:
        return ""
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
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise SpecError(f"{where}: expected a number, got {v!r}")
    return float(v)


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
        self.pal = PALETTES[theme]
        self.W = int(spec.get("w", spec.get("width", 640)))
        self.H = int(spec.get("h", spec.get("height", 400)))
        if not (160 <= self.W <= 4000 and 120 <= self.H <= 4000):
            raise SpecError("w must be 160..4000 and h 120..4000")
        self.out = []
        self.pre = str(spec.get("prefix", ""))
        self.suf = str(spec.get("suffix", ""))
        self.compact = spec.get("compact", True)

    def f(self, v, step=None):
        return fmt(v, step, self.pre, self.suf, self.compact)

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
            return [c.get(nm, self.pal[i % len(self.pal)]) for i, nm in enumerate(names)]
        if isinstance(c, list) and c:
            return [c[i % len(c)] for i in range(len(names))]
        return [self.pal[i % len(self.pal)] for i in range(len(names))]

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
        bg = self.s.get("bg", th["bg"])
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.W}" height="{self.H}" '
            f'viewBox="0 0 {self.W} {self.H}" font-family="{FONT}" font-size="12" '
            f'fill="{th["fg"]}" role="img"' + (f' aria-label="{escape(str(title))}"' if title else "") + ">"
        )
        parts = [head]
        if title:
            parts.append(f"<title>{escape(str(title))}</title>")
        if bg and bg != "none":
            parts.append(f'<rect width="100%" height="100%" fill="{bg}"/>')
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


class Plot:
    """Axes with a linear y scale and a categorical ("cat") or linear ("lin") x scale."""

    def __init__(self, c, top, ylo, yhi, xspec, thin=False, vgrid=False):
        s, th = c.s, c.th
        self.c = c
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
            c.line(self.L, yy, self.R, yy, th["grid"])
            c.text(self.L - 8, yy + 4, t, 11, th["muted"], "end")
        if self.kind == "lin":
            self.x0, self.x1 = self.xt[0], self.xt[-1]
            for v, t in zip(self.xt, xlab):
                xx = self.x(v)
                if vgrid:
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
        return self.B - (v - self.y0) / (self.y1 - self.y0) * self.H

    def x(self, v):
        return self.L + (v - self.x0) / (self.x1 - self.x0) * self.W

    def band(self, i):
        bw = self.W / self.n
        return self.L + i * bw, bw

    def finish(self, zero=True):
        zy = self.y(0) if zero and self.y0 <= 0 <= self.y1 else self.B
        self.c.line(self.L, zy, self.R, zy, self.c.th["axis"])


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


def bar(c, s):
    cats, ser = _sort(s, *cat_series(s))
    names = list(ser)
    cols = c.colors(names)
    stack = bool(s.get("stack")) and len(names) > 1
    ng = 1 if stack else len(names)
    horiz = s.get("type") == "hbar" or bool(s.get("horizontal"))
    if horiz and "h" not in s and "height" not in s:
        top0 = c.header()
        c.out.clear()
        per = 26 if ng == 1 else ng * 13 + 12
        c.H = int(max(200, top0 + (26 if _named(names) else 0) + len(cats) * per + 44 + (20 if s.get("xlabel") else 0)))
    top = c.header()
    if _named(names):
        top = c.legend(list(zip(names, cols)), top)
    if stack:
        pos = [sum(max(0, v[i] or 0) for v in ser.values()) for i in range(len(cats))]
        neg = [sum(min(0, v[i] or 0) for v in ser.values()) for i in range(len(cats))]
        lo, hi = min(0, min(neg)), max(0, max(pos))
    else:
        vals = [v for vs in ser.values() for v in vs if v is not None] or [0]
        lo, hi = min(0, min(vals)), max(0, max(vals))
    labels = s.get("labels", (ng == 1 and len(cats) <= 16) or (stack and len(cats) <= 16))
    if horiz:
        return _hbar(c, s, cats, ser, names, cols, stack, ng, lo, hi, top, labels)
    if labels:
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
            if labels and pa:
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
                c.bar(bx, p.y(0), bwj, p.y(0) - p.y(v), cols[j])
                if labels:
                    t = c.f(v)
                    if text_w(t, 11) <= inner + 6:
                        c.text(bx + bwj / 2, p.y(v) - 5 if v >= 0 else p.y(v) + 14, t, 11, anchor="middle")
    p.finish()


def _hbar(c, s, cats, ser, names, cols, stack, ng, lo, hi, top, labels):
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
    L, R, T, B = left, c.W - right, top, c.H - bottom
    if R - L < 60 or B - T < 40:
        raise SpecError("not enough room for the plot; increase w/h or shorten labels")
    xt, step = ticks(lo, hi, max(3, min(8, int((R - L) // 80))))
    x0, x1 = xt[0], xt[-1]
    X = lambda v: L + (v - x0) / (x1 - x0) * (R - L)  # noqa: E731
    for v in xt:
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
            if labels and pa:
                c.text(X(pa) + 5, gy + gh / 2 + 4, c.f(pa), 11)
        else:
            inner = gh / ng
            gap = min(3, inner * 0.12) if ng > 1 else 0
            for j, nm in enumerate(names):
                v = ser[nm][i]
                if v is None:
                    continue
                by, bhj = gy + j * inner + gap / 2, inner - gap
                c.bar(X(0), by, X(v) - X(0), bhj, cols[j], horizontal=True)
                if labels and bhj >= 9:
                    c.text(X(v) + (5 if v >= 0 else -5), by + bhj / 2 + 4, c.f(v), 11, anchor=None if v >= 0 else "end")
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
    top = c.header()
    if _named(names):
        top = c.legend(list(zip(names, cols)), top)
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
            up = [p.y(v) for v in cum[j]]
            dn = [p.y(v) for v in cum[j - 1]] if j else [base] * len(xs)
            poly = list(zip(xs, up)) + list(zip(xs, dn))[::-1]
            c.add(f'<path d="{_pathd(poly)}Z" fill="{col}" fill-opacity=".85"/>')
            c.add(f'<path d="{_pathd(list(zip(xs, up)))}" fill="none" stroke="{col}" stroke-width="1.5"/>')
            continue
        pts = [(x, None if v is None else p.y(v)) for x, v in zip(xs, vs)]
        for seg in _segments(pts):
            if area:
                poly = seg + [(seg[-1][0], base), (seg[0][0], base)]
                c.add(f'<path d="{_pathd(poly)}Z" fill="{col}" fill-opacity="{".22" if one else ".14"}"/>')
            c.add(
                f'<path d="{_pathd(seg)}" fill="none" stroke="{col}" stroke-width="2.25" '
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
            size = p[2] if len(p) > 2 and _isnum(p[2]) else None
            lab = next((q for q in p[2:] if isinstance(q, str)), None)
            out.append((_num(p[0], nm), _num(p[1], nm), size, lab))
        pts[str(nm)] = out
    names = list(pts)
    cols = c.colors(names)
    top = c.header()
    if _named(names):
        top = c.legend(list(zip(names, cols)), top)
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
    nb = int(s.get("bins") or math.ceil(math.log2(len(vals)) + 1))
    if not 1 <= nb <= 200:
        raise SpecError('"bins" must be 1..200')
    lo, hi = min(vals), max(vals)
    if hi == lo:
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
    mx = int(s.get("max_slices", 8))
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
    ri = r * float(s.get("hole", 0.6)) if donut else 0
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
        big = str(s.get("center", c.f(total)))
        sub = s.get("center_label", "Total" if "center" not in s else "")
        size = max(12, min(28, int(ri * 0.42), int((ri * 1.6) / max(1, text_w(big, 1)))))
        c.text(cx, cy + size * 0.35 - (7 if sub else 0), big, size, anchor="middle", weight=600)
        if sub:
            c.text(cx, cy + size * 0.35 + 9, fit(sub, 11, ri * 1.6), 11, th["muted"], "middle")


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
    else:
        pie(c, s, donut=t == "donut")
    return c.svg()
