# chart

`agent-tools chart '<json>' [-o out.svg|out.png]` prints the output path.
Spec can also be `@file.json` or `-` (stdin). `-o -` prints the SVG.

Types: bar hbar line area scatter pie donut histogram

Data (pick one):
- `"data":{"A":1,"B":2}` one series
- `"x":["Q1","Q2"],"series":{"2025":[1,2],"2026":[3,4]}` many series
- scatter: `"data":[[x,y],...]` or `"series":{"name":[[x,y,size?,"label"?],...]}`
- histogram: `"values":[...]`, optional `"bins":10`

Options: title subtitle xlabel ylabel w h(640x400) theme(light|dark)
prefix("$") suffix("%") stack(bar/area) sort(asc|desc) labels(bool)
colors([..] or {name:color}) zero(line from 0) dots(bool)
pie/donut: max_slices(8) hole(0.6) center center_label

Example: `agent-tools chart '{"type":"bar","title":"Sales","data":{"N":12,"S":9},"prefix":"$"}' -o sales.png`
