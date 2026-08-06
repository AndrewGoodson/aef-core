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
    "Data is embedded and complete. The renderer arrives in Stage 2 — "
    "until then this page reports what it holds rather than drawing it."
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
  --accent:#7fd1c1;--warn:#e0a94a;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme: light){
  :root{--ink:#f6f7f9;--panel:#fff;--line:#e2e6ec;--fg:#141922;--muted:#68717f;
        --accent:#178c78;--warn:#b57d10;}
}
:root[data-theme="dark"]{--ink:#0a0d12;--panel:#11151d;--line:#1e2531;--fg:#e6e9f0;
  --muted:#798294;--accent:#7fd1c1;--warn:#e0a94a;}
:root[data-theme="light"]{--ink:#f6f7f9;--panel:#fff;--line:#e2e6ec;--fg:#141922;
  --muted:#68717f;--accent:#178c78;--warn:#b57d10;}
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
"""

# `age()` is the only logic in the shell, and it is the load-bearing one: the
# page must report its own staleness rather than the age it had when it was
# built.
_JS = """
(function(){
var D = JSON.parse(document.getElementById('mind-data').textContent);
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
  'generated <span class="age">' + age(D.generated_at) + '</span>' +
  ' \\u00b7 data through <span class="age">' + age(D.data_through) + '</span>' +
  ' \\u00b7 expected report interval ' +
  Math.round(D.expected_report_interval_seconds / 60) + 'm' +
  ' \\u00b7 schema v' + D.schema_version;
})();
"""
