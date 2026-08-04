# ADR 0029: `aef init`'s `agent_name` argument is now validated against path traversal

## Status
Accepted

## Context
Adversarial pass on `aef/cli/init.py`/`aef/cli/doctor.py` (`doctor.py` came
back clean — verified against no-`CLAUDE.md`, no-`aef.yaml`, malformed
YAML, and a wrong-typed `aef.yaml`; all three produce a readable
`AgentConfigError`-derived message via `run_doctor`, none crash).

`run_init(agent_name, base_dir)` builds `agent_dir = base_dir.resolve() /
"agents" / agent_name` with zero validation on `agent_name` before it's
used as a filesystem path component — and `agent_name` is a raw CLI
positional argument (`aef/cli/main.py`: `p_init.add_argument("agent_name")`
→ `run_init(args.agent_name, ...)`), not something derived internally.
Reproduced directly, both confirmed to actually write files outside the
intended `<base_dir>/agents/` tree:

- `aef init ../../evil` resolved to a directory two levels *above*
  `<base_dir>/agents/` — files landed at a sibling of `base_dir` itself,
  not underneath it.
- `aef init /etc/evil` (or any absolute path) discarded `base_dir`
  entirely: `Path("/base") / "agents" / "/etc/evil"` evaluates to
  `/etc/evil` — a well-known `pathlib` gotcha where joining an absolute
  path as the right-hand operand of `/` drops everything to its left, not
  something this code guarded against.

Both cases proceed to actually `mkdir` and write `__init__.py`, `aef.yaml`,
and `graph.py` at the escaped location — a real arbitrary-file-write
primitive if `agent_name` is ever attacker-influenced (a scripted/
automated `aef init` call, or a careless copy-paste of an untrusted
string) rather than always hand-typed by a trusted developer.

Separately (same root cause, lower severity): `agent_name` is also
interpolated unescaped into generated Python source
(`_GRAPH_TEMPLATE`'s `id="{agent_name}"` and its module docstring) and
YAML (`_render_config`'s `objectives: "TODO: describe {agent_name}'s..."`).
A `"` in `agent_name` would have broken the generated Python file's string
literal — the same class of unescaped-interpolation bug as ADR 0028's
Mermaid injection, just in a different output format.

## Decision
`run_init` now validates `agent_name` against `^[A-Za-z_][A-Za-z0-9_]*$`
(a valid Python identifier) before doing anything else, raising a new
`InvalidAgentNameError(ValueError)` with a clear message naming the
offending value. This single constraint closes all three problems at
once: it rejects `/` and `\` (blocking both traversal and absolute-path
override), rejects `..` (which also wouldn't match the identifier
pattern), and rejects `"` and other quote/special characters (closing the
template-injection angle) — and it's the *correct* constraint
independent of security, since `agent_dir` becomes an importable Python
package (`agents.<agent_name>`), which requires a valid identifier
regardless.

`aef/cli/main.py`'s existing top-level `except Exception` in `main()`
already formats any raised exception as `error: {exc}` to stderr with
exit code 1 (confirmed by reading it, not assumed) — so
`InvalidAgentNameError` surfaces as a clean CLI error, not a traceback,
with no changes needed there.

## Consequences
- `aef init ../../evil` and `aef init /etc/evil` now fail immediately with
  a clear error instead of writing files outside the intended directory.
- Every existing call site already used a valid identifier (`"myagent"`)
  — grepped `tests/`/`examples/` for `run_init(` calls, all three existing
  ones pass — so this is a pure tightening, zero call sites needed
  updating.
- Hyphenated agent names (e.g. `"my-agent"`) are now rejected, which is a
  real behavior change from before (previously accepted, just also
  accepted `../../evil`) — but a hyphen was never actually usable anyway,
  since the directory needs to be an importable Python package name.
- 287/287 tests (up from 284/284; 3 new: path traversal, absolute path,
  a table of other invalid names), mypy --strict clean, ruff clean.

## Alternatives Considered
- **Resolve `agent_dir` and check it's still inside `base_dir/agents`
  after the fact**, instead of validating `agent_name` up front. Rejected:
  a post-hoc containment check doesn't address the template-injection
  angle (a `"` in `agent_name` breaking generated Python source has
  nothing to do with path containment), and validating the identifier
  constraint up front is simpler and catches both problems with one
  check instead of two different mechanisms.
- **Allow a broader safe character set (e.g. hyphens) instead of a strict
  Python identifier.** Rejected: the generated directory must already be
  a valid, importable Python package for `graph.py`'s `Graph(id=
  "{agent_name}", ...)` and any real usage of the scaffolded agent to
  work at all — a Python identifier isn't an arbitrary security choice
  here, it's the actual requirement.

## Confidence
High — both exploit shapes (relative traversal, absolute-path override)
were reproduced directly with real filesystem writes confirmed outside
the intended directory before any fix existed, the fix was verified to
reject both plus a table of other invalid names while accepting every
existing legitimate call site unchanged, and the existing top-level CLI
error handler was read (not assumed) to confirm the new exception
surfaces as a readable message.
