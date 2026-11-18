# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Table jig** (`jigstore table`): rows or a CSV/JSON file (`"from"`) to Markdown (default),
  SVG, PNG, HTML or CSV. Column formats money, percent (whole numbers), number, date, bar,
  sparkline; sign and scale coloring; totals; sort; highlight; image row limit 25 by default.
  CSV output neutralises spreadsheet formulas.
- The MCP server exposes a single `jig` tool (`{"jig": "chart" | "table", "spec": ...}`) so the
  per-turn schema stays the same size as the catalog grows. The old `chart` tool name still works.
- Benchmarks now include time: about 0.5 s with a spec instead of 5 to 30 s writing the output.

- Chart types: `waterfall` (with a closing `total`), `funnel`, `heatmap` and `sparkline`.
- Chart options: `highlight`, `refs` (reference lines), `stack: "percent"`,
  `curve: "smooth" | "step"`, `ymin`/`ymax`, `decimals`, `legend: top|bottom|none`,
  `grid`, `palette` (`colorblind`, `mono`, `warm`, `cool`) and `font`.
- Fuzz test for the renderer, plus a CI job that runs a longer fuzz with a new seed.
- `security` workflow: dependency review on PRs, zizmor workflow lint and fuzzing.
- Signed build provenance on releases.
- `AGENTS.md` for coding agents working on the repo; the usage prompt moved to
  `docs/agent-prompt.md`.

### Fixed

- Colors, background and font are validated before they reach SVG attributes. Before,
  a crafted color could inject markup into the SVG.
- Infinite and huge numbers, and wrongly typed options (`w`, `h`, `bins`, `hole`,
  `max_slices`), now raise `SpecError` instead of crashing.
- Very long labels no longer slow rendering down (truncation was quadratic).
- Values with a scaled suffix (`"suffix": "K"`) no longer show as "1.24KK".
- Scatter: negative bubble sizes and `null` coordinates raise `SpecError`.

### Earlier unreleased work

- MCP server (`jigstore mcp`) over stdio with no dependencies. Supports the
  2026-07-28 stateless protocol and the legacy `initialize` handshake (2024-11-05 to 2025-11-25).
- Project files: contributing guide, code of conduct, security policy, issue and PR templates.
- CI on Linux, macOS and Windows, lint with ruff, package build check, CodeQL, OpenSSF
  Scorecard, Dependabot, and a tag-driven release workflow.

### Changed

- The release workflow uses the `gh` CLI instead of a third-party release action.
- Renamed the project from agent-tools to Jigstore: package and import name `jigstore`,
  CLI `jigstore`, MCP output folder variable `JIGSTORE_OUT_DIR`.
- Minimum Python is 3.10.

## [0.1.0] - 2026-11-17

### Added

- Chart builder: bar, hbar, line, area, scatter, pie, donut and histogram from a JSON spec
  to SVG or PNG, with a CLI and a Python API.

[Unreleased]: https://github.com/jigstore/jigstore/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jigstore/jigstore/releases/tag/v0.1.0
