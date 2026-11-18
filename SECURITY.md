# Security policy

## Supported versions

Security fixes go into the latest release only.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/jigstore/jigstore/security/advisories/new).
Include the spec or input that triggers the problem and what you observed.

You can expect an acknowledgement within 5 working days and a fix or a plan within 30 days.

## Threat model

Specs are written by models, and models can be steered by text they read (a web page, an
email, a document). So every spec is treated as untrusted input, and the output (SVG) is
often embedded straight into HTML pages, chats and emails.

What the renderer guarantees, with tests in `tests/test_features.py` (class `Security`)
and `tests/test_fuzz.py`:

- **No markup injection.** Text is always escaped. Values that end up in SVG attributes
  (colors, background, font) are checked against strict patterns and refused otherwise.
  Output never contains script, event handlers or external references.
- **Bounded work.** Data points, canvas size, bins, labels and text length are capped, so
  a spec can't make rendering hang or use unbounded memory. Non-finite and huge numbers
  are refused.
- **Clean failures.** A bad spec raises `SpecError` with a one-line message. Any other
  exception is a bug. The fuzz test generates thousands of random and hostile specs and
  fails on anything else; CI runs a longer fuzz with a new seed on every push.
- **No file or network access** in the renderer. Only the CLI and MCP server write files,
  and the MCP server keeps writes inside `JIGSTORE_OUT_DIR` when it is set.

In scope for reports: anything that breaks one of the guarantees above.

## How the project protects itself

- `main` is protected: pull requests only, required CI, code owner review, no force pushes.
- First-time contributors' CI runs wait for maintainer approval.
- Every GitHub Action is pinned to a full commit SHA; workflows get read-only tokens by
  default; [zizmor](https://github.com/zizmorcore/zizmor) lints the workflows on every change.
- CodeQL, OpenSSF Scorecard, Dependabot, dependency review on PRs, and secret scanning
  with push protection.
- The core package has no runtime dependencies.
- Releases carry signed build provenance. Verify a download with
  `gh attestation verify <file> --repo jigstore/jigstore`.
