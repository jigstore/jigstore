# table

`jigstore table '<json>'` prints Markdown. `-o t.png|.svg|.html|.csv|.md` writes a file.

Rows: `"rows":[{"Region":"N","Revenue":12}]`, or `"columns":["Region","Revenue"],"rows":[["N",12]]`,
or `"from":"data.csv"` (or .json) to read a file instead of typing the data.

Column options: `"columns":[{"key":"Revenue","format":"money"}]`
format: text number money percent date bar sparkline. percent takes 12 or 95.5, not 0.12.
decimals (default 2 for money/percent) prefix suffix compact align(left|right|center)
color(sign|scale|"#hex") label width

Table options: total({"Region":"Total","Revenue":"sum"}, also avg min max) sort("Revenue"
or {"by":..,"order":"asc"}) highlight({"row":0} or {"where":{"Region":"N"}})
max_rows (images 25) title subtitle theme palette w zebra font

Example: `jigstore table '{"from":"q3.csv","total":{"Region":"Total","Revenue":"sum"}}' -o q3.png`
