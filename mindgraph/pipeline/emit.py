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
    "The graph below is the ACCUMULATED PRESENT \u2014 everything observed up to "
    "data_through, not a snapshot of an instant. Edge width is an edge's entire "
    "history; the activity core is what is happening now. The other two "
    "temporal modes are named below with what each would need to be drawn."
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


def _plain(value: float | int) -> str:
    """Render a window length without inventing precision.

    `14.0-day` reads as a measurement taken to one decimal place. It is a
    configured integer, and printing it as a float suggests the boundary is
    finer than it is.
    """
    return str(int(value)) if float(value).is_integer() else str(value)


def _coverage_strip(payload: dict[str, Any]) -> str:
    """The strip that answers "can I trust the rest of this page?".

    It leads, and that placement is the argument: every panel below it is
    conditional on coverage. A fleet reporting 1 of 4 makes everything
    underneath a sample rather than a measurement, and the reader needs that
    before they read anything else, not after scrolling past it.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import fleet  # noqa: PLC0415

    block = payload.get("fleet") or {}
    cover = block.get("coverage")
    rows = block.get("rows") or []
    if not cover:
        # No registry is not "everything is fine" — it is the one condition
        # under which nothing on this page is a measurement of anything.
        return (
            '<div class="strip unknown"><strong>No registry</strong>'
            "<span>the fleet cannot be assembled, so nothing below is a "
            "measurement of anything</span></div>"
        )

    tone = "ok" if cover["not_reporting"] == 0 else "bad"
    oldest = fleet.humanise(cover.get("oldest_overdue_seconds"))
    parts = [
        f"<b>{cover['fresh']}/{cover['total']}</b> reporting fresh",
        f"<b>{cover['stale']}</b> stale",
        f"<b>{cover['never']}</b> never reported",
        f"<b>{cover['error']}</b> telemetry error",
    ]
    if cover.get("unregistered"):
        parts.append(f"<b>{cover['unregistered']}</b> unregistered")
    parts.append(
        f"oldest overdue <b>{html.escape(oldest)}</b>" if oldest else "nothing overdue"
    )

    rails = {s["repo"]: s for s in (block.get("rails") or {}).get("segments", [])}
    cells = ""
    for row in rows:
        overdue = fleet.humanise(row.get("overdue_seconds"))
        seg = rails.get(str(row["repo"]), {})
        if seg.get("length_pct") is None:
            # No bar at all. Zero length would read as "held this state for no
            # time"; a full bar would invent a duration nobody measured.
            rail = '<div class="rail none" title="never reported"></div>'
        else:
            rail = (
                f'<div class="rail {html.escape(str(seg["treatment"]))}">'
                f'<i style="width:{seg["length_pct"]:.1f}%"></i></div>'
            )
        cells += (
            f'<tr class="fl {html.escape(str(row["treatment"]))}">'
            f'<td class="rp">{html.escape(str(row["repo"]))}</td>'
            f'<td class="st">{html.escape(str(row["state"]).replace("_", " "))}</td>'
            f'<td class="rl">{rail}</td>'
            f'<td class="ov">{html.escape(overdue) if overdue else "&mdash;"}</td>'
            f'<td class="er">{html.escape(str(row.get("telemetry_error") or ""))}</td>'
            "</tr>"
        )

    gap = (block.get("rails") or {}).get("gap")
    note = (
        f'<p class="caption" id="fleet-note">Rail length is how long each repo has held '
        f"its current state, scaled across the fleet. Not shown: {html.escape(str(gap))}.</p>"
        if gap
        else ""
    )
    return (
        f'<div class="strip {tone}"><strong>Coverage</strong>'
        f"<span>{' &middot; '.join(parts)}</span></div>"
        f'<div class="scroll"><table class="fleet" id="fleet-table">{cells}</table></div>'
        f"{note}"
    )


def _exception_queue(payload: dict[str, Any]) -> str:
    """Only what is abnormal, and a visible account of what was left out.

    An empty queue is only trustworthy if the reader can see what it CHOSE not
    to list. Otherwise "no exceptions" is indistinguishable from "nothing was
    checked" — which is this project's cardinal failure wearing a different
    hat.
    """
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import fleet  # noqa: PLC0415

    block = payload.get("exceptions") or {}
    items = block.get("items") or []
    excluded = block.get("excluded") or []
    gaps = block.get("gaps") or []
    sla = block.get("decision_sla_hours")

    if items:
        rows = "".join(
            f'<tr class="ex {html.escape(str(i["kind"]))}">'
            f'<td class="kd">{html.escape(str(i["kind"]).replace("_", " "))}</td>'
            f'<td class="sb">{html.escape(str(i["subject"]))}</td>'
            f'<td class="dt">{html.escape(str(i["detail"]))}</td>'
            f'<td class="ag">{html.escape(fleet.humanise(i.get("age_seconds")) or "")}</td>'
            "</tr>"
            for i in items
        )
        body = f'<div class="scroll"><table class="exq">{rows}</table></div>'
        head = f'<div class="strip bad"><strong>Exceptions</strong><span><b>{len(items)}</b> needing attention</span></div>'
    else:
        body = ""
        head = (
            '<div class="strip ok"><strong>Exceptions</strong>'
            "<span>nothing abnormal in this window</span></div>"
        )

    notes = []
    if excluded:
        notes.append(
            "Not listed, because these are the gate working as designed: "
            + ", ".join(html.escape(e.replace("_", " ")) for e in excluded)
            + "."
        )
    if sla:
        notes.append(f"A human decision counts as overdue after {int(sla)}h.")
    for gap in gaps:
        notes.append("Not detectable from the available data: " + html.escape(gap) + ".")

    footnote = f'<p class="caption exq-note">{" ".join(notes)}</p>' if notes else ""
    return head + body + footnote


def _cohort_flow(payload: dict[str, Any]) -> str:
    """Counted, reason-annotated branches. Nothing leaks; everything is
    accounted for."""
    block = payload.get("cohort")
    if not block:
        return ""

    total = block["proposed"]
    widest = max((b["pct"] for b in block["branches"]), default=1.0) or 1.0
    rows = ""
    for branch in block["branches"]:
        width = max(2.0, 100.0 * branch["pct"] / widest)
        band = branch["band"]
        band_text = (
            "no historical range"
            if band == "unknown"
            else f"expected {branch['expected_low']:.0f}\u2013{branch['expected_high']:.0f}%"
        )
        arrow = {"below": " \u25bc below", "above": " \u25b2 above", "in": "", "unknown": ""}[band]
        reason = (
            f'<span class="rsn">top reason: {html.escape(str(branch["reason_top"]))}</span>'
            if branch.get("reason_top")
            else ""
        )
        rows += (
            f'<div class="br {html.escape(branch["treatment"])}">'
            f'<div class="bl">{html.escape(branch["outcome"].replace("_", " "))}</div>'
            f'<div class="bb"><i style="width:{width:.1f}%"></i></div>'
            f'<div class="bn">{branch["count"]} <em>{branch["pct"]:.1f}%</em></div>'
            f'<div class="bx">{html.escape(band_text)}{arrow}{reason}</div>'
            "</div>"
        )

    # Rendered even at zero. A hidden zero is indistinguishable from a figure
    # nobody computed, which is this project's cardinal failure in miniature.
    tone = "neutral" if block["unclassified"] == 0 else "abnormal"
    rows += (
        f'<div class="br {tone}"><div class="bl">unclassified</div>'
        f'<div class="bb"></div>'
        f'<div class="bn">{block["unclassified"]}</div>'
        f'<div class="bx">proposals with no recorded outcome</div></div>'
    )
    if block["unaccounted"]:
        rows += (
            f'<div class="br abnormal"><div class="bl">unaccounted</div>'
            f'<div class="bb"></div><div class="bn">{block["unaccounted"]}</div>'
            f'<div class="bx">branches do not sum to the cohort \u2014 proposals are '
            f"missing between stages</div></div>"
        )

    notes = [
        "Rejection branches are neutral: a rejected proposal is the gate working. "
        "Red marks only the abnormal \u2014 a rollback, or a rate outside its own band."
    ]
    notes += [f"Not shown: {html.escape(g)}." for g in block.get("gaps", [])]

    window = (
        f' over {block["window_days"]} days' if block.get("window_days") else ""
    )
    return (
        f'<div class="strip" id="cohort-head"><strong>Cohort</strong>'
        f"<span><b>{total}</b> proposed{window}, every one accounted for below</span></div>"
        f'<div class="flow" id="cohort-flow">{rows}</div>'
        f'<p class="caption" id="cohort-note">{" ".join(notes)}</p>'
    )


def _stability(payload: dict[str, Any]) -> str:
    """A band chart. Explicitly not a control chart, and it says why.

    Every metric declares what backs it: an observation with a band, an
    observation alone, or nothing. A metric that has not been compared renders
    dashed and reads `no baseline` — never as one that passed.
    """
    block = payload.get("stability")
    if not block or not block.get("metrics"):
        return ""

    rows = ""
    for metric in block["metrics"]:
        obs, low, high = metric["observation"], metric["band_low"], metric["band_high"]
        status = metric["status"]
        if low is not None and high is not None and obs is not None:
            # Scale the strip so the band occupies the middle half, which puts
            # an out-of-band reading visibly outside it rather than merely near
            # an edge.
            span = max(high - low, 1e-6)
            lo_v, hi_v = low - span, high + span
            pos = max(0.0, min(100.0, 100.0 * (obs - lo_v) / (hi_v - lo_v)))
            band_left = 100.0 * (low - lo_v) / (hi_v - lo_v)
            band_w = 100.0 * span / (hi_v - lo_v)
            gauge = (
                f'<div class="gg"><i class="bd" style="left:{band_left:.1f}%;'
                f'width:{band_w:.1f}%"></i>'
                f'<i class="pt" style="left:{pos:.1f}%"></i></div>'
            )
            band_text = f"band {low:.0f}\u2013{high:.0f}{metric['unit']}"
        else:
            gauge = '<div class="gg none"></div>'
            band_text = "no baseline"

        value = "\u2014" if obs is None else f"{obs:g}{metric['unit']}"
        note = (
            f'<span class="rsn">{html.escape(str(metric["note"]))}</span>'
            if metric.get("note")
            else ""
        )
        rows += (
            f'<div class="br {html.escape(metric["treatment"])}">'
            f'<div class="bl">{html.escape(metric["label"])}</div>'
            f"{gauge}"
            f'<div class="bn">{html.escape(value)}</div>'
            f'<div class="bx">{html.escape(band_text)}'
            f'{"" if status in ("in", "unknown") else " &mdash; <b>" + status + " band</b>"}'
            f"{note}</div></div>"
        )

    absent = "".join(
        f'<div class="br unknown"><div class="bl">{html.escape(a["metric"])}</div>'
        f'<div class="gg none"></div><div class="bn">\u2014</div>'
        f'<div class="bx">not recorded &mdash; {html.escape(a["why"])}</div></div>'
        for a in block.get("absent", [])
    )

    notes = [
        html.escape(block["why_not_control_chart"]).capitalize() + ".",
        f"{block['banded_count']} metric(s) have a band; {block['unbanded_count']} have a "
        "reading with nothing to compare it against.",
    ]
    return (
        f'<div class="strip" id="stability-head"><strong>Stability</strong>'
        f"<span>band chart &middot; no series recorded, so no trends and no run rules</span></div>"
        f'<div class="flow" id="stability-bands">{rows}{absent}</div>'
        f'<p class="caption" id="stability-note">{" ".join(notes)}</p>'
    )


def _comparison(payload: dict[str, Any]) -> str:
    """One side of a two-sided question, named as one.

    No ratio, no delta, no arrow, no second bar — each of those renders a
    comparison in a place where no comparison exists, and the reader would
    supply the missing half from imagination, favourably.
    """
    block = payload.get("comparison")
    if not block:
        return ""

    rate = block.get("durable_per_review_hour")
    rate_text = "\u2014" if rate is None else f"{rate:g}"
    rows = (
        f'<div class="br unknown"><div class="bl">durable changes</div>'
        f'<div class="gg none"></div><div class="bn">{html.escape(rate_text)}</div>'
        f'<div class="bx">per human review hour &mdash; <b>no comparator recorded</b>'
        f'<span class="rsn">{html.escape(block["counterfactual_note"])}</span></div></div>'
    )
    if block.get("rollback_rate_pct") is not None:
        rows += (
            f'<div class="br neutral"><div class="bl">change-fail rate</div>'
            f'<div class="gg none"></div>'
            f'<div class="bn">{block["rollback_rate_pct"]:.1f}%</div>'
            f'<div class="bx">merged changes later rolled back &mdash; the DORA pair for '
            f"throughput, and both halves are loop-side so neither needs a comparator</div></div>"
        )
    if block.get("durable_yield_pct") is not None:
        rows += (
            f'<div class="br neutral"><div class="bl">durable yield</div>'
            f'<div class="gg none"></div>'
            f'<div class="bn">{block["durable_yield_pct"]:.1f}%</div>'
            f'<div class="bx">of proposals that merged and stayed merged</div></div>'
        )
    for name in block.get("absent", []):
        rows += (
            f'<div class="br unknown"><div class="bl">{html.escape(name)}</div>'
            f'<div class="gg none"></div><div class="bn">\u2014</div>'
            f'<div class="bx">not recorded</div></div>'
        )

    return (
        f'<div class="strip unknown" id="comparison-head">'
        f'<strong>{html.escape(block["label"])}</strong>'
        f"<span>one side of a two-sided question &middot; not a causal claim</span></div>"
        f'<div class="flow" id="comparison-panel">{rows}</div>'
        f'<p class="caption" id="comparison-note">'
        f'{html.escape(block["why_observational"]).capitalize()}. '
        f"No ratio or verdict is shown, because there is nothing to compare against.</p>"
    )


def _modes(payload: dict[str, Any]) -> str:
    """Name the temporal frame, and say what the unavailable modes would need.

    A reader who does not know which temporal frame they are looking at will
    assume the most flattering one. "This path is thick" means it has carried a
    lot EVER, not that it is busy now — and those read identically at a glance.
    """
    block = payload.get("modes")
    if not block:
        return ""

    rows = ""
    for mode in block["modes"]:
        current = mode["key"] == block["current"]
        state = "showing" if current else ("available" if mode["available"] else "not available")
        cls = "neutral" if current else "unknown"
        detail = html.escape(mode["describes"])
        if mode.get("requires"):
            detail += (
                f'<span class="rsn">needs {html.escape(mode["requires"])}</span>'
            )
        if mode.get("partial"):
            detail += f'<span class="rsn">{html.escape(mode["partial"])}</span>'
        rows += (
            f'<div class="br {cls}"><div class="bl">{html.escape(mode["label"])}</div>'
            f'<div class="gg none"></div>'
            f'<div class="bn">{html.escape(state)}</div>'
            f'<div class="bx">{detail}</div></div>'
        )

    return (
        f'<div class="strip" id="modes-head"><strong>Temporal mode</strong>'
        f"<span><b>{block['available_count']}</b> of {len(block['modes'])} modes available "
        f"&middot; showing the accumulated present</span></div>"
        f'<div class="flow" id="modes-panel">{rows}</div>'
        f'<p class="caption" id="modes-note">{html.escape(block["note"])}.</p>'
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
        f"<code>{_plain(payload.get('dormancy_window_days', 14))}-day</code> window. "
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
        "__STRIP__", _coverage_strip(payload)
    ).replace(
        "__EXCEPTIONS__", _exception_queue(payload)
    ).replace(
        "__COHORT__", _cohort_flow(payload)
    ).replace(
        "__STABILITY__", _stability(payload)
    ).replace(
        "__COMPARISON__", _comparison(payload)
    ).replace(
        "__MODES__", _modes(payload)
    ).replace(
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
  <header class="head flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="eyebrow">agent mind graph</p>
      <h1>__GRAPH__</h1>
      <p class="stamp" id="stamp"></p>
    </div>
    <button type="button" class="tbtn" id="theme-toggle" aria-pressed="false">
      <span class="tdot" id="theme-dot"></span><span id="theme-label">theme</span>
    </button>
  </header>
  __STRIP__
  __EXCEPTIONS__
  <p class="notice">__NOTICE__</p>
  __COHORT__
  __STABILITY__
  __COMPARISON__
  __MODES__
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
  <p class="caption" id="encoding-legend">__LEGEND__</p>
  <section>
    <h2>Embedded payload</h2>
    <div class="scroll"><table>__ROWS__</table></div>
  </section>
  <footer>Read-only. No controls, no requests. Every age above is computed in the
  page from the embedded timestamps, so this file reports its own staleness.
  <br>This page contains no animation of any kind &mdash; no transitions, no keyframes,
  no timers, no animation frames. `prefers-reduced-motion` is satisfied
  unconditionally rather than by a rule that could be forgotten, and every state
  here is fully interpretable without having watched anything happen.</footer>
</main>
<script type="application/json" id="mind-data">__DATA__</script>
<script>__JS__</script>
</body>
</html>
"""

# The stylesheet is COMPILED, not hand-written: `styles/input.css` is Tailwind
# source, and `tools/build-css` renders it to `styles/tailwind.css`, which is
# committed and inlined here verbatim.
#
# Compiling at build time would put npm on the critical path of
# `python pipeline/build.py` and put the network on the path of a project whose
# entire point is that it needs neither. So the CSS is generated in a separate,
# explicit step and checked in; the Python build stays offline and pure.
def _load_css() -> str:
    from pathlib import Path as _P

    sheet = _P(__file__).resolve().parent.parent / "styles" / "tailwind.css"
    if not sheet.is_file():
        raise FileNotFoundError(
            f"{sheet} is missing. It is the COMPILED Tailwind stylesheet and it is "
            f"committed, not generated on demand — run tools/build-css to rebuild it. "
            f"Emitting the page without it would produce an unstyled document that "
            f"still passed every structural check."
        )
    return sheet.read_text(encoding="utf-8")


_CSS = _load_css()


# `age()` is the only logic in the shell, and it is the load-bearing one: the
# page must report its own staleness rather than the age it had when it was
# built.
_JS = """
(function(){
var D = JSON.parse(document.getElementById('mind-data').textContent);
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim();}

// Read from the stylesheet rather than restated here, so the canvas cannot
// drift onto a different family from the DOM. One typeface on the page.
var SANS = css('--font-sans') || 'ui-sans-serif,system-ui,sans-serif';

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
      cx.font = '600 10px ' + SANS;
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
      cx.font = '600 10px ' + SANS;
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
    cx.font = '600 ' + Math.max(8, Math.round(r*0.8)) + 'px ' + SANS;
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
      cx.font = '600 9px ' + SANS;
      cx.textAlign = 'center'; cx.textBaseline = 'middle';
      cx.fillText(R.birth_flag, tx + tw/2, ty + 7);
    }

    // Label.
    cx.fillStyle = css('--fg');
    cx.font = '500 11px ' + SANS;
    cx.textBaseline = 'top';
    cx.fillText(n.id, x, y + r + 5);
  }
}
draw();

// --- theme switch -----------------------------------------------------------
// The palette lives in CSS custom properties, so the DOM re-styles itself the
// moment `data-theme` changes. The CANVAS does not: it read its colours through
// css() at draw time and baked them into pixels. That seam is the whole reason
// this is more than a one-line toggle — without the redraw the page would show
// a light chrome wrapped around a dark graph.
//
// The choice is NOT persisted. Browser storage of every kind is banned in this
// artifact, so the theme lasts the life of the page and no longer. That is a
// deliberate consequence of the read-only constraint rather than an oversight,
// and the button says so in its title instead of leaving the reader to find out
// by reloading.
(function(){
  var root = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  var label = document.getElementById('theme-label');
  if (!btn) { return; }

  var media = window.matchMedia('(prefers-color-scheme: dark)');

  function current(){
    // Explicit choice wins; otherwise whatever the operator's environment asked
    // for. Read fresh each time so the button never fights the media query.
    return root.getAttribute('data-theme') || (media.matches ? 'dark' : 'light');
  }
  function paint(){
    var now = current();
    label.textContent = now === 'dark' ? 'dark' : 'light';
    btn.setAttribute('aria-pressed', now === 'dark' ? 'true' : 'false');
    btn.title = 'Switch to ' + (now === 'dark' ? 'light' : 'dark')
              + ' theme. Not saved \\u2014 this file writes nothing.';
  }
  btn.addEventListener('click', function(){
    root.setAttribute('data-theme', current() === 'dark' ? 'light' : 'dark');
    paint();
    draw();  // the canvas holds baked pixels, not live colours
  });
  // Following the environment while no explicit choice has been made.
  media.addEventListener('change', function(){
    if (!root.getAttribute('data-theme')) { paint(); draw(); }
  });
  paint();
})();
})();
"""
