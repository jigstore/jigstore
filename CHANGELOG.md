# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- MCP server (`jigstore mcp`) over stdio with no dependencies. Supports the
  2026-07-28 stateless protocol and the legacy `initialize` handshake (2024-11-05 to 2025-11-25).
- Project files: contributing guide, code of conduct, security policy, issue and PR templates.
- CI on Linux, macOS and Windows, lint with ruff, package build check, CodeQL, OpenSSF
  Scorecard, Dependabot, and a tag-driven release workflow.

### Changed

- Renamed the project from agent-tools to Jigstore: package and import name `jigstore`,
  CLI `jigstore`, MCP output folder variable `JIGSTORE_OUT_DIR`.
- Minimum Python is 3.10.

## [0.1.0] - 2026-11-17

### Added

- Chart builder: bar, hbar, line, area, scatter, pie, donut and histogram from a JSON spec
  to SVG or PNG, with a CLI and a Python API.

[Unreleased]: https://github.com/ankit22sharma/jigstore/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ankit22sharma/jigstore/releases/tag/v0.1.0
