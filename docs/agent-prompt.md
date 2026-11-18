# Jigstore: prompt for agents that use it

Paste this into your agent's instructions. It is about 230 tokens.

Use these CLI tools instead of generating the output yourself. They are cheaper and deterministic.

- `jigstore list` shows tools. `jigstore docs <tool>` shows the spec format.
- Charts: `jigstore chart '<json>' -o out.png` (or `.svg`). Prints the path.
  Types: bar hbar line area scatter pie donut histogram waterfall funnel heatmap sparkline.
  `{"type":"bar","title":"T","data":{"A":1,"B":2}}` or `"x":[..],"series":{"name":[..]}`.
- Tables: `jigstore table '<json>'` prints Markdown; `-o t.png|.svg|.html|.csv` writes a file.
  `{"rows":[{"Region":"N","Revenue":12}]}` or `{"from":"data.csv"}` to read saved data instead of retyping it.
  Formats: money percent(12 = 12%) number date bar sparkline. `"total":{"Region":"Total","Revenue":"sum"}`.
- On `error:` read the message, fix the spec, retry once.
