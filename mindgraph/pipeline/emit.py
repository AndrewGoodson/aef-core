"""Stage 1.4 — wrap the payload in the document shell.

One file. The data goes into a `<script type="application/json">` block and
nothing else reads anything from anywhere: no request, no storage, no external
reference. Open it with the network disconnected and it behaves identically,
because there is nothing for the network to serve.

## The staleness rule, and why it is not decoration

Every visible age is computed **in the page, from the embedded timestamps**. A
file generated on Tuesday and opened on Friday must say "3 days old" — not
because that is nicer, but because a static artifact that reports a fixed age
lies more convincingly the longer it sits. The report forbids labelling it
live for the same reason: a snapshot claiming freshness is the cardinal
anti-pattern with a clock on it.

## Escaping

The payload is JSON inside a `<script>` element, which is a different parsing
context from HTML text. `json.dumps` escapes neither `</script>` inside a
string value nor U+2028/U+2029 — both terminate the element or the statement
and turn escaped-looking data into executable markup. Handled explicitly, and
verified against the real strings rather than paraphrases of them.
"""

from __future__ import annotations

import html
import json
from typing import Any

# No renderer yet. Stage 2 replaces this block; until then the page says so
# plainly. An empty canvas would be indistinguishable from a broken one, and
# this whole project is about not letting absence look like something else.
STAGE_NOTICE = (
    "A node that appeared recently carries a static age tab \u2014 not a "
    "pulsing halo, which would be confusable with an alarm, invisible in a "
    "screenshot, and would imply live motion in a file that has none. The tab "
    "says how old the node was when this picture was taken. Dashboard panels "
    "arrive in Stage 4."
)


def json_for_script(payload: Any) -> str:
    """JSON safe to embed inside a `<script>` element."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return (
        encoded.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _legend_text(payload: dict[str, Any]) -> str:
    """The legend, DERIVED from the contract's constants and from edges that
    actually exist in this graph.

    Section 4.2 requires concrete worked examples with real windows and
    numbers, and every transform and cap printed. It would be easier to type
    those into the template — and they were, which made the legend a second
    copy of the constants that nobody compared. Change `RADIUS_K` and the page
    would keep printing the old coefficient while drawing the new one: a legend
    that lies is worse than no legend, because it is believed.

    The worked examples are picked from the payload rather than invented, so
    every number below is one the reader can find on the canvas.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import contract  # noqa: PLC0415

    missing = [
        f"{e.get('source')}->{e.get('target')}" for e in payload["edges"] if "render" not in e
    ]
    if missing:
        # Found by extending the verifier: emit() crashed on a payload whose
        # edges had no render block. Refused rather than tolerated — a legend
        # built from a payload the contract never resolved would silently omit
        # its worked examples, and a legend with no examples is precisely the
        # bare "brighter = more active" the report forbids.
        raise ValueError(
            f"edges have no render block: {missing}. The contract resolves these during "
            f"the build; a payload without them was not produced by this pipeline, and a "
            f"legend derived from it would quietly lose its worked examples."
        )
    edges = [e for e in payload["edges"] if e["render"]["rail_width"] is not None]
    busiest = max(edges, key=lambda e: e["lifetime_traversal_count"], default=None)
    abandoned = next(
        (e for e in edges if e["edge_state"] == "dormant"),
        None,
    )
    never = next((e for e in edges if e["edge_state"] == "never_observed"), None)

    examples = []
    if busiest is not None:
        examples.append(
            f"<code>{busiest['lifetime_traversal_count']} traversals, last today</code> "
            f"&rarr; widest rail on this graph, core at full brightness"
        )
    if abandoned is not None:
        examples.append(
            f"<code>{abandoned['lifetime_traversal_count']} traversals, none in the window</code> "
            f"&rarr; rail just as wide, core gone dark &mdash; abandoned, not absent"
        )
    if never is not None:
        examples.append(
            "<code>0 observed</code> &rarr; hairline, dashed, open rings, and no core at all"
        )
    examples.append(
        "<code>no telemetry</code> &rarr; patterned line with a midpoint ?, and it "
        "claims nothing about volume"
    )

    return (
        f"Node radius = <code>{contract.RADIUS_MIN} + {contract.RADIUS_K} &#215; "
        f"sqrt(log1p(executions))</code>, capped at <code>{contract.RADIUS_CAP}</code>. "
        f"Edge rail = <code>log1p(traversals)</code>, which never decays. "
        f"Core brightness = recency against a "
        f"<code>{payload.get('dormancy_window_days', 14)}-day</code> window. "
        f"Fill carries measured state only; border carries how much we can see. "
        f"<br>Worked examples from this graph: " + "; ".join(examples) + "."
    )


def _summary_rows(payload: dict[str, Any]) -> str:
    edge_states: dict[str, int] = {}
    for edge in payload["edges"]:
        edge_states[edge["edge_state"]] = edge_states.get(edge["edge_state"], 0) + 1
    reasons: dict[str, int] = {}
    for node in payload["nodes"]:
        reasons[node["layout_reason"]] = reasons.get(node["layout_reason"], 0) + 1

    rows = [
        ("graph", payload["graph_id"]),
        ("layout version", str(payload["layout_version"])),
        ("nodes", str(len(payload["nodes"]))),
        ("edges", str(len(payload["edges"]))),
    ]
    rows += [(f"edges · {k}", str(v)) for k, v in sorted(edge_states.items())]
    rows += [(f"nodes · {k}", str(v)) for k, v in sorted(reasons.items())]
    return "".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows
    )


def emit(payload: dict[str, Any]) -> str:
    """The document. Content is escaped for HTML; the payload for a script."""
    return _SHELL.replace("__CSS__", _CSS).replace("__JS__", _JS).replace(
        "__DATA__", json_for_script(payload)
    ).replace("__ROWS__", _summary_rows(payload)).replace(
        "__LEGEND__", _legend_text(payload)
    ).replace(
        "__NOTICE__", html.escape(STAGE_NOTICE)
    ).replace("__GRAPH__", html.escape(str(payload["graph_id"])))


_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__GRAPH__ — agent mind graph</title>
<style>__CSS__</style>
</head>
<body>
<main>
  <header class="head">
    <p class="eyebrow">agent mind graph</p>
    <h1>__GRAPH__</h1>
    <p class="stamp" id="stamp"></p>
  </header>
  <p class="notice">__NOTICE__</p>
  <div class="stage"><canvas id="c" width="900" height="560"></canvas></div>
  <div class="legend">
    <span class="lg"><i class="sw normal"></i>normal — executed within the window</span>
    <span class="lg"><i class="sw stale"></i>stale — instrumented, nothing recent</span>
    <span class="lg"><i class="sw unknown"></i>no telemetry — makes no claim</span>
    <span class="lg"><i class="sw border"></i>border = evidence quality, never health</span>
    <span class="lg"><i class="ln rail"></i>rail = cumulative traffic (never decays)</span>
    <span class="lg"><i class="ln core"></i>core = recency (decays to nothing)</span>
    <span class="lg"><i class="ln dashed"></i>&#9711; never taken (open rings)</span>
    <span class="lg"><i class="ln cap"></i>&#9866; retired by a person</span>
    <span class="lg">? nothing was watching</span>
    <span class="lg"><i class="tab"></i>age when this picture was taken</span>
    <span class="lg"><i class="gt"></i>[H] human gate &#8212; &#8230; awaiting, &#10003; approved, &#10007; rejected</span>
  </div>
  <p class="caption">__LEGEND__</p>
  <section>
    <h2>Embedded payload</h2>
    <div class="scroll"><table>__ROWS__</table></div>
  </section>
  <footer>Read-only. No controls, no requests. Every age above is computed in the
  page from the embedded timestamps, so this file reports its own staleness.</footer>
</main>
<script type="application/json" id="mind-data">__DATA__</script>
<script>__JS__</script>
</body>
</html>
"""

_CSS = """
:root{
  --ink:#0a0d12;--panel:#11151d;--line:#1e2531;--fg:#e6e9f0;--muted:#798294;
  --accent:#7fd1c1;--warn:#e0a94a;--ok:#57c98b;--stale:#8d93a3;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme: light){
  :root{--ink:#f6f7f9;--panel:#fff;--line:#e2e6ec;--fg:#141922;--muted:#68717f;
        --accent:#178c78;--warn:#b57d10;--ok:#1d9a63;--stale:#6f7686;}
}
:root[data-theme="dark"]{--ink:#0a0d12;--panel:#11151d;--line:#1e2531;--fg:#e6e9f0;
  --muted:#798294;--accent:#7fd1c1;--warn:#e0a94a;--ok:#57c98b;--stale:#8d93a3;}
:root[data-theme="light"]{--ink:#f6f7f9;--panel:#fff;--line:#e2e6ec;--fg:#141922;
  --muted:#68717f;--accent:#178c78;--warn:#b57d10;--ok:#1d9a63;--stale:#6f7686;}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--fg);font:15px/1.55 var(--sans)}
main{max-width:1100px;margin:0 auto;padding:2rem 1.25rem 3rem;
  display:flex;flex-direction:column;gap:1rem}
.eyebrow{font:500 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--accent);margin:0 0 .5rem}
h1{font-size:1.55rem;margin:0;letter-spacing:-.02em;text-wrap:balance}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  margin:1.5rem 0 .5rem;font-weight:600}
.head{border-bottom:1px solid var(--line);padding-bottom:1rem}
.stamp{margin:.5rem 0 0;font:12px/1.5 var(--mono);color:var(--muted)}
.stamp .age{color:var(--warn)}
.notice{margin:0;padding:.7rem .9rem;border:1px dashed var(--line);border-radius:9px;
  color:var(--muted);font-size:.85rem;background:var(--panel)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;font-size:.85rem;min-width:320px}
th,td{text-align:left;padding:.35rem 1.25rem .35rem 0;border-bottom:1px solid var(--line);
  font-weight:400}
th{color:var(--muted);font-family:var(--mono)}
td{font-variant-numeric:tabular-nums}
footer{margin-top:1.5rem;padding-top:1rem;border-top:1px solid var(--line);
  color:var(--muted);font-size:.78rem;max-width:62ch}
.stage{border:1px solid var(--line);border-radius:12px;overflow:hidden;
  background:var(--panel)}
canvas{display:block;width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:1rem;font:11px/1 var(--mono);
  letter-spacing:.04em;color:var(--muted)}
.lg{display:flex;align-items:center;gap:.4rem}
.sw{width:11px;height:11px;border-radius:50%;flex:0 0 auto;display:inline-block}
.sw.normal{background:var(--ok)}
.sw.stale{background:var(--stale)}
.sw.unknown{background:transparent;border:1.5px dashed var(--muted)}
.sw.border{background:transparent;border:2px solid var(--fg)}
.caption{margin:0;color:var(--muted);font-size:.78rem;max-width:74ch;line-height:1.7}
.ln{width:18px;height:0;flex:0 0 auto;display:inline-block}
.ln.rail{border-top:5px solid var(--line)}
.ln.core{border-top:2px solid var(--accent)}
.ln.dashed{border-top:2px dashed var(--muted)}
.ln.cap{border-top:2px solid var(--muted)}
.gt{width:20px;height:11px;flex:0 0 auto;display:inline-block;
  border:1.5px solid var(--warn);border-radius:1px}
.tab{width:18px;height:10px;flex:0 0 auto;display:inline-block;
  background:var(--accent);border-radius:1px}
code{font-family:var(--mono);font-size:.95em}
"""

# `age()` is the only logic in the shell, and it is the load-bearing one: the
# page must report its own staleness rather than the age it had when it was
# built.
_JS = """
(function(){
var D = JSON.parse(document.getElementById('mind-data').textContent);
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim();}

function age(iso){
  var then = Date.parse(iso);
  if (isNaN(then)) { return 'unknown'; }
  var s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 90) { return Math.round(s) + 's ago'; }
  if (s < 5400) { return Math.round(s/60) + 'm ago'; }
  if (s < 172800) { return Math.round(s/3600) + 'h ago'; }
  return Math.round(s/86400) + 'd ago';
}
document.getElementById('stamp').innerHTML =
  'generated \u003cspan class="age"\u003e' + age(D.generated_at) + '\u003c/span\u003e' +
  ' \u00b7 data through \u003cspan class="age"\u003e' + age(D.data_through) + '\u003c/span\u003e' +
  ' \u00b7 expected report interval ' +
  Math.round(D.expected_report_interval_seconds / 60) + 'm' +
  ' \u00b7 schema v' + D.schema_version;

// The construction is decided by the contract at BUILD time and baked in.
// There are exactly two branches and neither has a default, so there is no
// path in this file that draws a healthy circle over an absent field.
function fillFor(state){
  if (state === 'normal') { return css('--ok'); }
  if (state === 'stale') { return css('--stale'); }
  if (state === 'never_executed') { return css('--stale'); }
  return null;   // never a colour; the caller must take the unknown branch
}

var GLYPH = {agent:'\u25cf', gate:'\u25a0', terminal:'\u25b6'};

function hatch(cx, x, y, r){
  // Hatching, not a fill and not a glow: it reads as "no measurement" at any
  // size and survives a greyscale screenshot.
  cx.save();
  cx.beginPath(); cx.arc(x, y, r, 0, 6.283185); cx.clip();
  cx.strokeStyle = css('--muted'); cx.lineWidth = 1;
  for (var i = -r*2; i < r*2; i += 5) {
    cx.beginPath(); cx.moveTo(x+i, y-r); cx.lineTo(x+i+r*2, y+r); cx.stroke();
  }
  cx.restore();
}

function draw(){
  var cv = document.getElementById('c');
  var cx = cv.getContext('2d');
  cx.clearRect(0, 0, cv.width, cv.height);

  // EDGES FIRST, so nodes sit on top of their own connections.
  //
  // Two independent channels, and the independence is the feature. Rail width
  // is cumulative and never decays; core luminance is recency and does. A
  // single blended number would collapse an abandoned path and a never-taken
  // one onto the same faint line, which is the one confusion this artifact
  // exists to prevent.
  var pos = {};
  for (var k = 0; k < D.nodes.length; k++) { pos[D.nodes[k].id] = D.nodes[k]; }

  for (var e = 0; e < D.edges.length; e++) {
    var ed = D.edges[e], ER = ed.render;
    var a = pos[ed.source], b = pos[ed.target];
    if (!a || !b) { continue; }

    var dx = b.x - a.x, dy = b.y - a.y;
    var len = Math.sqrt(dx*dx + dy*dy) || 1;
    var ux = dx/len, uy = dy/len;          // along the edge
    var px = -uy, py = ux;                 // perpendicular to it

    if (ER.rail_width === null) {
      // UNKNOWN COVERAGE — alternating pattern, midpoint '?', and NO width
      // claim. Absence of telemetry is not evidence of absent traffic, so
      // this edge asserts nothing about volume at all.
      cx.strokeStyle = css('--muted'); cx.lineWidth = 1.4;
      cx.setLineDash([2, 4]); cx.globalAlpha = 0.6;
      cx.beginPath(); cx.moveTo(a.x, a.y); cx.lineTo(b.x, b.y); cx.stroke();
      cx.setLineDash([]); cx.globalAlpha = 1;
      var mx = (a.x + b.x)/2, my = (a.y + b.y)/2;
      cx.fillStyle = css('--panel');
      cx.beginPath(); cx.arc(mx, my, 7, 0, 6.283185); cx.fill();
      cx.strokeStyle = css('--muted'); cx.lineWidth = 1;
      cx.setLineDash([2, 2]);
      cx.beginPath(); cx.arc(mx, my, 7, 0, 6.283185); cx.stroke();
      cx.setLineDash([]);
      cx.fillStyle = css('--muted');
      cx.font = '600 10px ui-monospace,monospace';
      cx.textAlign = 'center'; cx.textBaseline = 'middle';
      cx.fillText('?', mx, my);
      continue;
    }

    // 1. HISTORY RAIL — cumulative, monotonic, never decays.
    // NEVER OBSERVED is dashed: a hairline that is also a different KIND of
    // line, so the state reads without measuring the width against another
    // edge. Width alone would demand a comparison the eye should not have to
    // make.
    var neverTaken = (ed.edge_state === 'never_observed');
    cx.strokeStyle = css('--line');
    cx.lineWidth = 1 + ER.rail_width * 0.95;
    cx.lineCap = 'round';
    if (neverTaken) { cx.setLineDash([4, 4]); }
    cx.beginPath(); cx.moveTo(a.x, a.y); cx.lineTo(b.x, b.y); cx.stroke();
    cx.setLineDash([]);

    // 2. ACTIVITY CORE — recency only. null means NEVER fired, which draws no
    // core at all; 0.0 means fired long ago, which draws a dark one. Those are
    // different claims and they get different marks.
    if (ER.core_luminance !== null) {
      cx.globalAlpha = 0.15 + ER.core_luminance * 0.85;
      cx.strokeStyle = css('--accent');
      cx.lineWidth = Math.max(1, ER.rail_width * 0.32);
      cx.beginPath(); cx.moveTo(a.x, a.y); cx.lineTo(b.x, b.y); cx.stroke();
      cx.globalAlpha = 1;
    }
    cx.lineCap = 'butt';

    // 3. GATE — a RECTANGLE interrupting the edge (Section 3c, verdict B).
    // Deliberately not a diamond: a diamond is the flowchart symbol for a
    // decision that BRANCHES, and this gate chooses no path. It is a
    // checkpoint an accountable human signed, and it interrupts the line to
    // say the traffic stopped here for a person.
    if (ed.gate) {
      var gx = (a.x + b.x)/2, gy = (a.y + b.y)/2;
      var gw = 30, gh = 15;
      cx.save();
      cx.translate(gx, gy);
      cx.rotate(Math.atan2(dy, dx));
      cx.fillStyle = css('--panel');
      cx.fillRect(-gw/2, -gh/2, gw, gh);
      cx.strokeStyle = ed.gate.disposition === 'awaiting' ? css('--warn') : css('--muted');
      cx.lineWidth = ed.gate.disposition === 'awaiting' ? 2 : 1.3;
      cx.strokeRect(-gw/2, -gh/2, gw, gh);
      cx.restore();
      // The glyph is drawn UNROTATED so it stays readable on any edge angle.
      cx.fillStyle = ed.gate.disposition === 'awaiting' ? css('--warn') : css('--fg');
      cx.font = '600 10px ui-monospace,monospace';
      cx.textAlign = 'center'; cx.textBaseline = 'middle';
      cx.fillText(ed.gate.glyph, gx, gy);
    }

    // 4. ENDPOINT MARKERS — the state, readable without comparison.
    if (neverTaken) {
      // OPEN rings: the path is configured and has carried nothing. Open
      // rather than filled, because filled would read as a terminus.
      cx.strokeStyle = css('--muted'); cx.lineWidth = 1.2;
      cx.beginPath(); cx.arc(a.x + ux*14, a.y + uy*14, 3.2, 0, 6.283185); cx.stroke();
      cx.beginPath(); cx.arc(b.x - ux*14, b.y - uy*14, 3.2, 0, 6.283185); cx.stroke();
    } else if (ed.edge_state === 'retired') {
      // A perpendicular bar, like a buffer stop. Retirement is a human
      // decision recorded in config, never inferred from silence — so it gets
      // a mark that reads as deliberate rather than as decay.
      var rx = b.x - ux*16, ry = b.y - uy*16;
      cx.strokeStyle = css('--muted'); cx.lineWidth = 2;
      cx.beginPath();
      cx.moveTo(rx + px*6, ry + py*6);
      cx.lineTo(rx - px*6, ry - py*6);
      cx.stroke();
    }
  }

  for (var i = 0; i < D.nodes.length; i++) {
    var n = D.nodes[i], R = n.render, x = n.x, y = n.y, r = R.radius;
    var unknown = (R.construction === 'unknown');

    // 1. FILL — measured operational state only.
    if (unknown) {
      hatch(cx, x, y, r);
    } else {
      var col = fillFor(R.fill_state);
      if (col === null) { hatch(cx, x, y, r); unknown = true; }
      else { cx.fillStyle = col; cx.beginPath(); cx.arc(x,y,r,0,6.283185); cx.fill(); }
    }

    // 2. BORDER — evidence quality, never health.
    cx.strokeStyle = unknown ? css('--muted') : css('--line');
    cx.lineWidth = 1.6;
    if (R.border === 'full') { cx.setLineDash([]); }
    else if (R.border === 'partial') { cx.setLineDash([5,3]); }
    else if (R.border === 'new') { cx.setLineDash([]); }
    else { cx.setLineDash([2,4]); }
    cx.beginPath(); cx.arc(x, y, r, 0, 6.283185); cx.stroke();
    if (R.border === 'new') {
      cx.beginPath(); cx.arc(x, y, r + 3.5, 0, 6.283185); cx.stroke();
    }
    cx.setLineDash([]);

    // 3. INTERIOR GLYPH — role lives inside, so outlines stay uniform.
    cx.fillStyle = unknown ? css('--muted') : css('--ink');
    cx.font = '600 ' + Math.max(8, Math.round(r*0.8)) + 'px ui-monospace,monospace';
    cx.textAlign = 'center'; cx.textBaseline = 'middle';
    cx.fillText(unknown ? '?' : (GLYPH[R.glyph] || '\u25cf'), x, y);

    // BIRTH TAB — static, baked at build time against generated_at. Not a
    // halo: a halo would be confusable with an alarm, invisible in a
    // screenshot, and would imply live motion in a file that has none.
    if (R.birth_flag) {
      var tw = 8 + R.birth_flag.length * 7;
      var tx = x + r - 2, ty = y - r - 13;
      cx.fillStyle = css('--accent');
      cx.fillRect(tx, ty, tw, 13);
      cx.fillStyle = css('--ink');
      cx.font = '600 9px ui-monospace,monospace';
      cx.textAlign = 'center'; cx.textBaseline = 'middle';
      cx.fillText(R.birth_flag, tx + tw/2, ty + 7);
    }

    // Label.
    cx.fillStyle = css('--fg');
    cx.font = '500 11px ui-monospace,monospace';
    cx.textBaseline = 'top';
    cx.fillText(n.id, x, y + r + 5);
  }
}
draw();
})();
"""
