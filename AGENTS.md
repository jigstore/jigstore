# AGENTS.md

> Maintainers: project status, decisions and plans are in the private `jigstore-hq` repo
> (sibling folder `../jigstore-hq`). Read its `STATUS.md` first and update it before you finish.
> Contributors without access can ignore this; everything needed to work on the code is below.

Instructions for coding agents working **on** this repo. (To **use** Jigstore from an
agent, see `docs/agent-prompt.md`.)

## What this is

Deterministic tools ("jigs") that AI agents call instead of writing output token by token.
Python 3.10+, standard library only at runtime.

## Commands

```sh
PYTHONPATH=src python -m unittest discover -s tests   # all tests, ~1 s
ruff check . && ruff format --check .                 # lint (ruff 0.17.5)
python scripts/build_examples.py                      # regenerate examples/*.svg; CI fails if stale
JIGSTORE_FUZZ_SEED=7 JIGSTORE_FUZZ_N=20000 PYTHONPATH=src python -m unittest tests.test_fuzz
```

Run all three before you finish. There is no build step.

## Layout

| Path | What |
|---|---|
| `src/jigstore/chart/render.py` | the chart jig: spec in, SVG string out. `render()` dispatches by `type` |
| `src/jigstore/chart/png.py` | optional PNG via cairosvg or rsvg-convert |
| `src/jigstore/chart/USAGE.md` | the spec format agents read. Shipped in the package |
| `src/jigstore/table/render.py` | the table jig: rows or a CSV/JSON file in, md/svg/html/csv out (`render_table`, `save_table`) |
| `examples/tables.json`, `examples/data/` | table examples and the CSV they read |
| `src/jigstore/cli.py` | `jigstore list / docs / chart / mcp` |
| `src/jigstore/mcp.py` | stdio MCP server with one `jig` tool; `JIGS` maps names to handlers. `Toolset` lets the hosted service reuse it |
| `src/jigstore/__init__.py` | `CATALOG` of jigs and `__version__` |
| `examples/specs.json` | one spec per example; covers every chart type |
| `tests/` | `test_chart` (examples, CLI), `test_features` (options, security), `test_table`, `test_mcp`, `test_fuzz` (charts and tables) |

## Rules that tests enforce

- **Deterministic.** Same spec, same bytes. No randomness, time or environment in output.
- **No runtime dependencies.** Optional extras only (`[png]`).
- **Token budgets.** Each `USAGE.md` stays under 300 tokens (~1,200 characters). The whole
  MCP tool list stays under 150 tokens (`test_tool_schema_is_small`): add jigs to the
  `jig` tool's enum, never as new tools. Every example SVG stays under 8 KB.
- **Files.** Only the CLI and the local MCP server may read files (`from`), always
  through a `base_dir` and never outside it. Library calls default to refusing `from`, which
  is what the hosted service relies on.
- **Every bad spec raises `SpecError`** with one line that says how to fix it. Any other
  exception is a bug; the fuzz test checks this.
- **Untrusted input.** Escape all text with `escape()`. Never put a spec value into an
  SVG attribute unless it is a number formatted with `n()` or passed through `color()`
  or a similar strict check. Cap list sizes and string lengths (`MAX_POINTS`, `MAX_TEXT`).
- **Every chart type has an example** in `examples/specs.json` (`test_every_type_covered`).

## Adding a chart type

1. Write `def mytype(c, s)` in `render.py`. Use `cat_series(s)` to read data, `c.header()`,
   `c.place_legend()`, and `Plot` for axes. Read numeric options with `opt_num()`.
2. Add it to `TYPES` and to the dispatch in `render()`.
3. Add an example to `examples/specs.json`, tests to `tests/test_features.py`, and fuzz
   coverage if it reads new keys (`tests/test_fuzz.py`).
4. Update `USAGE.md`, the type list in `mcp.py` `TOOLS`, `docs/agent-prompt.md` and
   `CHANGELOG.md`. Check the token budgets still pass.
5. Run `python scripts/build_examples.py` and look at the new SVG.

## Adding a new jig

Create `src/jigstore/<name>/` with `render.py`, `USAGE.md` and `__init__.py` (the table
jig is the model to copy), add it to `CATALOG`, a CLI subcommand in `cli.py`, a handler in
`JIGS` and the `jig` enum in `mcp.py`, examples in `scripts/build_examples.py`, tests and fuzz.
Read `CONTRIBUTING.md` first: new jigs need an issue agreeing on the spec format.

## Conventions

- Short, imperative commit messages; one logical change per PR; add a `CHANGELOG.md` line.
- `main` is protected. Work on a branch and open a PR; don't push to `main`.
- Commits by agents should still be reviewed by a person before merge.
