# Security policy

## Supported versions

Security fixes go into the latest release only.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/ankit22sharma/jigstore/security/advisories/new).
Include the spec or input that triggers the problem and what you observed.

You can expect an acknowledgement within 5 working days and a fix or a plan within 30 days.

## Scope

Specs come from models, and models can be steered by untrusted text, so treat every
spec as untrusted input. Relevant issues include:

- markup or script injection into the generated SVG through labels or titles
- writing files outside the path the caller asked for
- input that makes rendering hang or use unbounded memory
