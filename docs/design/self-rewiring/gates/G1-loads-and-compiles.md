> **⚠ REVISED — read `../04-review-and-self-coding-redesign.md` §2.4 first.**
> The authoritative G1 definition is now: loads, `Graph.compile()`/`validate()`,
> `mypy --strict` clean, and the existing suite passes. §2 below is **wrong** and
> is corrected inline. Retained for provenance.

# G1 — Loads and compiles

The cheapest structural check: does the proposed wiring produce a legal
graph at all?

## 1. Exact definition

**Reject** iff the candidate manifest fails to:

1. **load** — every import ref resolves; `Node`/`Edge` objects construct
   without raising (notably `NodeContractError`, which already enforces
   "non-pure node needs an `idempotency_key_fn`", `contracts.py:204-210`);
2. **compile** — `Graph.compile()` succeeds, which runs `validate()`
   (`graph.py:44-74`).

`validate()` checks: `entry_node` is declared; every `edge.from_node` and
every `edge.targets` member is declared; every `fallback_node_id` is
declared (`graph.py:46-59`).

**Accept** otherwise.

## 2. Known limits of `validate()` — and what G1 adds

`validate()` deliberately does **not** check (`../00-current-state.md` §1):
reachability, cycles, duplicate edges, END-reachability, condition
validity, or priority collisions. Two of those matter enough for a
*machine-proposed* graph that G1 should add them as **additional
structural assertions**:

| Added check | Why a proposer makes it necessary | Status |
|---|---|---|
| **Every node reachable from `entry_node`** | A proposer can orphan a node by rewiring around it; an orphan is dead weight and usually a mistake | **~~Dropped~~** — see correction |
| **`END` reachable** from `entry_node` | A rewiring that removes every path to `END` produces a graph that can only ever terminate via `max_steps` — a `GraphExecutionError`, discovered at runtime rather than at gate time | **~~Dropped~~** — see correction |

> **✗ CORRECTION (04 §1.9). Both added checks are dropped: neither is
> computable from the edge set.** Routing is chosen by node code, not
> authorised by edges — `_resolve_route` returns the `Route` the node
> supplied (`executor.py:233-260`). Consequences:
> - **`END`-reachability is undecidable statically.** `END` never appears in
>   any `Edge`; it is returned by a node body. A graph with no edge to `END`
>   may terminate on its first step, and a graph with an edge to `END` may
>   never route there.
> - **Node reachability is unsound in the same direction, and additionally
>   produces false positives:** `fallback_node_id` targets bypass edge
>   resolution entirely (ADR 0036), so a fallback-only node is correctly
>   wired yet would be flagged an orphan and the candidate wrongly rejected.
>
> G1 keeps only what is actually decidable: load, `compile()`/`validate()`,
> `mypy --strict`, and the existing suite green.

Cycles are **not** rejected — cycles are legitimate (bounded by
`max_steps`: the step loop at `executor.py:107`, the exhaustion raise at
`executor.py:182`) and `test_max_steps_exceeded_raises` already pins that
behaviour.

**Note:** these additional checks live in the gate, not in
`Graph.validate()`, so kernel behaviour is unchanged for hand-authored
graphs. Whether they should later be promoted into `validate()` itself is
**Q-G1-1**.

## 3. Failure behaviour

Auto-reject; report the exact validation error (`GraphValidationError`
already joins all errors, `graph.py:60-61`) or the unresolved ref. Cheap
enough to run on every candidate before anything expensive.

## 4. Gaming, and mitigations

Low surface. A malformed graph simply fails. The one subtlety: a proposer
could add an unreachable node to make a diff *look* smaller in effect than
it is — mitigated by the reachability check above and by the diff being
rendered in full for the owner.

## 5. How this gate is tested

1. Manifest with an edge to an undeclared node ⇒ reject
   (`GraphValidationError`).
2. Manifest with `entry_node` not in nodes ⇒ reject.
3. Non-pure node with no `idempotency_key_fn` ⇒ reject
   (`NodeContractError`).
4. ~~Manifest orphaning a node ⇒ reject.~~ **Dropped** — and inverted into a
   known-bad test: a graph whose only path to a node is a `fallback_node_id`
   ⇒ **accept** (proves G1 does not falsely reject correct fallback wiring).
5. ~~Manifest with no path to `END` ⇒ reject.~~ **Dropped** — inverted: a
   graph with no `Edge` to `END` whose entry node returns `END` ⇒ **accept**.
6. A graph containing a legitimate cycle ⇒ **accept** (cycles are allowed).
7. A valid manifest ⇒ accept, and the produced `Graph` is structurally
   equal to the equivalent hand-built one (proves the loader is faithful).

## 6. Open question

- ~~**Q-G1-1** — should reachability / END-reachability be promoted into
  `Graph.validate()` for all graphs?~~ **Closed by the correction above:**
  neither check is decidable from the edge set, so there is nothing to
  promote. Had it been promoted into `validate()`, every graph using a
  `fallback_node_id`-only node — a supported pattern — would have failed to
  compile.
