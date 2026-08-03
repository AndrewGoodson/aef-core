# ADR 0018: `aef run` adds the current directory to `sys.path` before importing

## Status
Accepted

## Context
Auditing `aef/cli/doctor.py` and `init.py` led to actually running the two
commands together end-to-end — `aef init test_agent` followed by
`aef run agents.test_agent.graph --objective "..."`, exactly what a new
user would do — rather than just reading the code. It failed outright:
`error: No module named 'agents'`.

Root cause: `aef` runs as an installed console-script entry point.
`sys.path[0]` for a console script is the script's own directory (e.g.
`.venv/bin`), not the caller's current working directory — unlike
`python script.py` or `python -m module`, both of which put CWD on
`sys.path` automatically. `run_graph_module` never accounted for this, so
a module one directory below wherever the user is standing — exactly what
`aef init` produces — could never be found.

This directly breaks the pairing the CLI itself implies: `aef init` scaffolds
`agents/<name>/graph.py` and nothing else in `aef init`'s own help text or
generated files suggests the user needs to do anything else before
`aef run agents.<name>.graph` works.

## Decision
`run_graph_module` now inserts `Path.cwd()` at the front of `sys.path` (if
not already present) before calling `importlib.import_module`, matching
the behavior a plain `python`/`python -m` invocation gives for free. This
is a deliberate, documented side effect on `sys.path` — the trade-off
accepted in exchange for `aef run <module>` meaning what it looks like it
means: run this module, relative to where you're standing.

Also fixed a smaller, related asymmetry while auditing the same file:
`aef doctor`'s `claude_md_present` check reported just a bare file path on
failure, while its `agent_config` check gives an actionable remediation
("run `aef adopt` or `aef init`"). Brought `claude_md_present`'s failure
message to the same standard.

## Consequences
- `aef init <name>` followed by `aef run agents.<name>.graph` now works
  without the user needing to set `PYTHONPATH` or otherwise intervene —
  verified by actually running both commands in sequence in a scratch
  directory, not inferred from reading the code.
- Every call to `run_graph_module` now has the side effect of mutating
  process-global `sys.path` (idempotently — checked for the CWD already
  being present first). This is intentional and matches ordinary Python
  invocation semantics, not something callers need to guard against.

## Alternatives Considered
- **Add a `--dir PATH` option to `aef run` instead of using CWD.**
  Rejected as an unnecessary extra step for the common case: `cd` into
  the project and run `aef run <module>` is the natural, already-expected
  workflow; CWD is the right implicit signal, matching how `python -m`
  already behaves.
- **Tell users to set `PYTHONPATH` manually / document the workaround.**
  Rejected: the whole point of `aef init` + `aef run` is a working
  two-command loop; documenting around a bug instead of fixing it doesn't
  serve the adoption-path goal this CLI exists for.

## Confidence
High — reproduced with the real installed console script, fixed, and
re-verified the same way (not just via the unit test suite, though a
regression test using `monkeypatch.chdir` — deliberately not
`syspath_prepend`, to avoid masking the exact bug — locks in the fix too).
