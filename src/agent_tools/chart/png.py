"""Optional PNG output. Uses cairosvg if installed, else the rsvg-convert binary."""

from __future__ import annotations

import os
import shutil
import subprocess

from .render import SpecError, render


def to_png(svg: str, scale: float = 2.0) -> bytes:
    """Rasterise an SVG string. scale=2 gives crisp output on high-DPI screens."""
    try:
        import cairosvg  # type: ignore
    except ImportError:
        cairosvg = None
    if cairosvg is not None:
        return cairosvg.svg2png(bytestring=svg.encode(), scale=scale)
    exe = shutil.which("rsvg-convert")
    if exe:
        r = subprocess.run([exe, "-z", str(scale), "-f", "png"], input=svg.encode(), capture_output=True, check=False)
        if r.returncode == 0:
            return r.stdout
        raise SpecError(f"rsvg-convert failed: {r.stderr.decode(errors='replace').strip()}")
    raise SpecError(
        "PNG needs cairosvg (pip install 'agent-tools[png]') or rsvg-convert "
        "(brew install librsvg / apt install librsvg2-bin); or write .svg instead"
    )


def save(spec, path: str, scale: float = 2.0) -> str:
    """Render spec to path. The extension (.svg or .png) picks the format. Returns the path."""
    svg = render(spec)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        data = to_png(svg, scale)
        with open(path, "wb") as f:
            f.write(data)
    elif ext in (".svg", ""):
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    else:
        raise SpecError(f"output must end in .svg or .png, got {path!r}")
    return path
