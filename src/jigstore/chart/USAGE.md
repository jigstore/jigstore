# chart

`jigstore chart '<json>' [-o out.svg|out.png]` prints the output path.
Spec can be `@file.json` or `-` (stdin). `-o -` prints the SVG.

Types: bar hbar line area scatter pie donut histogram waterfall funnel heatmap sparkline

Data:
- `"data":{"A":1,"B":2}` one series
- `"x":["Q1","Q2"],"series":{"2025":[1,2],"2026":[3,4]}` many series (heatmap: one per row)
- scatter: `"series":{"name":[[x,y,size?,"label"?]]}`; histogram: `"values":[..]`,`"bins":10`
- waterfall: changes, `"total":"Net"` adds a total bar

Options: title subtitle xlabel ylabel w h theme(light|dark) palette(default|colorblind|mono|warm|cool)
colors([..]|{series:color}) prefix suffix decimals legend(top|bottom|none) grid(bool) labels(bool)
ymin ymax refs([{"value":100,"label":"Target"}]) highlight("East"|[..]) sort(asc|desc)
stack(true|"percent") curve(linear|smooth|step) zero dots font bg("none")
pie/donut: max_slices hole center center_label. sparkline: area dot (default 120x32)

Example: `jigstore chart '{"type":"bar","data":{"N":12,"S":9},"highlight":"N"}' -o s.png`
