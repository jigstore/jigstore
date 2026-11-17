import io
import json
import os
import tempfile
import unittest

from agent_tools.mcp import TOOLS, serve

MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}


def run(*msgs):
    out = io.StringIO()
    serve(io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\n"), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


class Legacy(unittest.TestCase):
    def test_handshake_list_call(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.svg")
            r = run(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "chart", "arguments": {"spec": {"data": {"a": 1}}, "out": out}},
                },
            )
            self.assertEqual([m["id"] for m in r], [1, 2, 3])
            self.assertEqual(r[0]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(r[1]["result"]["tools"][0]["name"], "chart")
            self.assertFalse(r[2]["result"]["isError"])
            self.assertEqual(r[2]["result"]["content"][0]["text"], out)
            self.assertTrue(os.path.exists(out))

    def test_unknown_version_falls_back(self):
        r = run({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}})
        self.assertEqual(r[0]["result"]["protocolVersion"], "2025-11-25")


class Modern(unittest.TestCase):
    def test_discover(self):
        r = run({"jsonrpc": "2.0", "id": "d", "method": "server/discover", "params": {"_meta": MODERN_META}})[0][
            "result"
        ]
        self.assertEqual(r["resultType"], "complete")
        self.assertIn("2026-07-28", r["supportedVersions"])
        self.assertEqual(r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "agent-tools")

    def test_stateless_list_and_call(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": MODERN_META}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "_meta": MODERN_META,
                        "name": "chart",
                        "arguments": {
                            "spec": {"type": "pie", "data": {"a": 1, "b": 2}},
                            "out": os.path.join(d, "p.svg"),
                        },
                    },
                },
            )
            self.assertEqual(r[0]["result"]["resultType"], "complete")
            self.assertIn("ttlMs", r[0]["result"])
            self.assertEqual(r[1]["result"]["resultType"], "complete")
            self.assertFalse(r[1]["result"]["isError"])

    def test_unsupported_version(self):
        r = run(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01"}},
            }
        )[0]
        self.assertEqual(r["error"]["code"], -32022)
        self.assertIn("2026-07-28", r["error"]["data"]["supported"])


class Behaviour(unittest.TestCase):
    def test_bad_spec_returns_usage(self):
        r = run(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "chart", "arguments": {"spec": {"type": "nope"}}},
            }
        )[0]["result"]
        self.assertTrue(r["isError"])
        self.assertIn("unknown type", r["content"][0]["text"])
        self.assertIn("Types:", r["content"][0]["text"])

    def test_default_output_dir(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["AGENT_TOOLS_OUT_DIR"] = d
            try:
                r = run(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "chart", "arguments": {"spec": {"data": {"a": 1}}}},
                    }
                )[0]["result"]
            finally:
                del os.environ["AGENT_TOOLS_OUT_DIR"]
            path = r["content"][0]["text"]
            self.assertTrue(path.startswith(os.path.realpath(d)) or path.startswith(d))
            self.assertTrue(os.path.exists(path))

    def test_out_dir_blocks_escape(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["AGENT_TOOLS_OUT_DIR"] = d
            try:
                r = run(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "chart", "arguments": {"spec": {"data": {"a": 1}}, "out": "../escape.svg"}},
                    }
                )
            finally:
                del os.environ["AGENT_TOOLS_OUT_DIR"]
            self.assertTrue(r[0]["result"]["isError"])
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(d), "escape.svg")))

    def test_only_svg_or_png(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "chart",
                        "arguments": {"spec": {"data": {"a": 1}}, "out": os.path.join(d, "x.py")},
                    },
                }
            )
            self.assertTrue(r[0]["result"]["isError"])

    def test_unknown_method_and_tool(self):
        r = run(
            {"jsonrpc": "2.0", "id": 1, "method": "nope"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}},
        )
        self.assertEqual(r[0]["error"]["code"], -32601)
        self.assertEqual(r[1]["error"]["code"], -32602)

    def test_parse_error(self):
        out = io.StringIO()
        serve(io.StringIO("{not json\n"), out)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], -32700)

    def test_tool_schema_is_small(self):
        # The schema sits in the model's context every turn: keep it under ~150 tokens.
        self.assertLess(len(json.dumps(TOOLS, separators=(",", ":"))) // 4, 150)


if __name__ == "__main__":
    unittest.main()
