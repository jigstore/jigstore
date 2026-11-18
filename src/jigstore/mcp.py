"""Thin MCP server over stdio, with no dependencies.

Dual-era: answers the legacy `initialize` handshake (protocol 2025-11-25 and earlier)
and stateless per-request `_meta` requests (2026-07-28). Tool descriptions are kept short
because a client puts them in the model's context on every turn; the full spec format is
returned only when a call fails.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys

from . import __version__

MODERN = ["2026-07-28"]
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "jigstore", "version": __version__}
PV = "io.modelcontextprotocol/protocolVersion"

TOOLS = [
    {
        "name": "chart",
        "description": (
            "Render a chart from a small JSON spec; returns the file path. "
            'Example spec: {"type":"bar","title":"Sales","data":{"N":12,"S":9}}. '
            "Types: bar hbar line area scatter pie donut histogram waterfall funnel heatmap sparkline. "
            "Bad specs return the full format."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "object", "description": "chart spec"},
                "out": {"type": "string", "description": "path ending .svg or .png (optional)"},
                "view": {"type": "boolean", "description": "also return a PNG to look at"},
            },
            "required": ["spec"],
        },
    }
]


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class ToolError(Exception):
    """A tool failed in a way the model can fix; returned as isError content."""


def _usage():
    from importlib import resources

    return resources.files("jigstore.chart").joinpath("USAGE.md").read_text(encoding="utf-8")


def _out_path(out, svg):
    """Resolve the output path. With JIGSTORE_OUT_DIR set, writes stay inside it."""
    root = os.environ.get("JIGSTORE_OUT_DIR")
    base = os.path.realpath(os.path.expanduser(root)) if root else os.getcwd()
    if not out:
        out = f"chart-{hashlib.sha256(svg.encode()).hexdigest()[:10]}.svg"
    path = os.path.realpath(os.path.join(base, os.path.expanduser(out)))
    if root and os.path.commonpath([base, path]) != base:
        raise ToolError(f"error: out must be inside {base}")
    return path


def call_chart(args: dict, ctx: dict | None = None) -> list:
    from .chart import SpecError, render, save, to_png

    spec = args.get("spec")
    try:
        if isinstance(spec, str):
            spec = json.loads(spec)
        svg = render(spec)
        out = _out_path(args.get("out"), svg)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        save(spec, out)
        content = [{"type": "text", "text": out}]
        if args.get("view"):
            try:
                png = to_png(svg, 1.0)
            except SpecError as e:
                content.append({"type": "text", "text": f"(no preview: {e})"})
            else:
                content.append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(png).decode()})
        return content
    except (SpecError, ValueError, OSError) as e:
        raise ToolError(f"error: {e}\n\n{_usage()}") from None


HANDLERS = {"chart": call_chart}
INSTRUCTIONS = "Call chart with a JSON spec instead of writing SVG yourself."


class Toolset:
    """What a server exposes. The hosted service passes its own toolset to reuse this protocol code.

    Each handler is called as handler(arguments, ctx) and returns MCP content, or raises ToolError.
    """

    def __init__(self, tools, handlers, server_info=None, instructions=INSTRUCTIONS):
        self.tools, self.handlers = tools, handlers
        self.server_info = server_info or SERVER_INFO
        self.instructions = instructions


LOCAL = Toolset(TOOLS, HANDLERS)


def handle(msg: dict, state: dict, toolset: Toolset = LOCAL):
    """Return a response dict, or None for notifications. `state` is passed to handlers as ctx."""
    method, mid = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}
    if mid is None:  # notification (initialized, cancelled, ...): nothing to send
        return None
    try:
        result = dispatch(method, params, state, toolset)
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except RpcError as e:
        err = {"code": e.code, "message": e.message}
        if e.data is not None:
            err["data"] = e.data
        return {"jsonrpc": "2.0", "id": mid, "error": err}


def dispatch(method, params, state, toolset: Toolset = LOCAL):
    ts = toolset
    meta = params.get("_meta") or {}
    version = meta.get(PV)
    modern = version is not None

    if method == "initialize":
        want = params.get("protocolVersion")
        state["legacy"] = want if want in LEGACY else LEGACY[0]
        return {
            "protocolVersion": state["legacy"],
            "capabilities": {"tools": {}},
            "serverInfo": ts.server_info,
            "instructions": ts.instructions,
        }
    if method == "ping":
        return {}
    if modern and version not in MODERN:
        raise RpcError(-32022, "Unsupported protocol version", {"supported": MODERN + LEGACY, "requested": version})

    def done(r):
        if modern or method == "server/discover":
            r["resultType"] = "complete"
            r.setdefault("_meta", {})["io.modelcontextprotocol/serverInfo"] = ts.server_info
        return r

    if method == "server/discover":
        return done(
            {
                "supportedVersions": MODERN + LEGACY,
                "capabilities": {"tools": {}},
                "instructions": ts.instructions,
                "ttlMs": 3600000,
                "cacheScope": "public",
            }
        )
    if method == "tools/list":
        r = {"tools": ts.tools}
        if modern:
            r.update(ttlMs=3600000, cacheScope="public")
        return done(r)
    if method == "tools/call":
        name = params.get("name")
        fn = ts.handlers.get(name)
        if fn is None:
            raise RpcError(-32602, f"Unknown tool: {name}")
        try:
            return done({"content": fn(params.get("arguments") or {}, state), "isError": False})
        except ToolError as e:
            return done({"content": [{"type": "text", "text": str(e)}], "isError": True})
    raise RpcError(-32601, f"Method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    if stdin is None:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    state: dict = {}
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if isinstance(msg, list):  # JSON-RPC batch (legacy clients only)
                resp = [r for r in (handle(m, state) for m in msg) if r is not None] or None
            elif isinstance(msg, dict):
                resp = handle(msg, state)
            else:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        if resp is not None:
            stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
