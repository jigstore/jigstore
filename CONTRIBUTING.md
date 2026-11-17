# Contributing

Thanks for helping. Bug reports, new chart options and new tools are all welcome. If you'd
rather support the work another way, you can [buy me a coffee](https://buymeacoffee.com/ankit22sharma).

## Setup

```sh
git clone https://github.com/jigstore/jigstore && cd jigstore
python -m venv .venv && . .venv/bin/activate
pip install -e . ruff pre-commit
pre-commit install
```

## Before you open a pull request

```sh
python -m unittest discover -s tests
ruff check . && ruff format --check .
python scripts/build_examples.py   # if rendering changed; commit the updated SVGs
```

Open an issue first for anything larger than a bug fix, so we can agree on the spec
format before you write code. Spec formats are hard to change once agents depend on them.

## Rules for tools

A tool belongs here if an agent would otherwise generate the output token by token.

- **Deterministic.** The same spec always gives the same output.
- **No runtime dependencies** in the core. Optional extras are fine (`[png]`).
- **Short input, short output.** The CLI prints a path or a one-line error.
- **Errors say how to fix the spec,** in one line, because a model reads them.
- **`USAGE.md` stays under 300 tokens.** It is what an agent reads to learn the tool.
- **The MCP tool description stays under 150 tokens.** Clients load it on every turn.

Each tool lives in `src/jigstore/<name>/` with `USAGE.md`, a CLI subcommand, an
entry in `CATALOG` and the MCP `TOOLS` list, examples and tests.

## Commits and releases

Use short, imperative commit messages. Add a line under `Unreleased` in `CHANGELOG.md`
for user-visible changes. Maintainers release by bumping `__version__`, moving the
changelog entries under the new version, and pushing a `vX.Y.Z` tag.

## How changes reach `main`

`main` is protected (see `.github/rulesets/main.json`): every change goes through a pull
request, CI must pass, a code owner must approve, review threads must be resolved, and PRs
are squash-merged. Force pushes and branch deletion are blocked. First-time contributors'
CI runs wait for a maintainer to approve them.

By contributing you agree that your work is released under the MIT License and that you
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
