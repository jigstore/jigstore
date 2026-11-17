# Jigstore (for AI agents)

Use these CLI tools instead of generating the output yourself. They are cheaper and deterministic.

- `jigstore list` shows tools. `jigstore docs <tool>` shows the spec format.
- Charts: `jigstore chart '<json>' -o out.png` (or `.svg`). Prints the path.
  Types: bar hbar line area scatter pie donut histogram.
  `{"type":"bar","title":"T","data":{"A":1,"B":2}}` or `"x":[..],"series":{"name":[..]}`.
- On `error:` read the message, fix the spec, retry once.
