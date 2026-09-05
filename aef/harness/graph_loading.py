"""The ONE way anything in this repo turns a graph entrypoint into a module.

ADR 0177, erratum on ADR 0168. ADR 0168 §M4 taught `aef run` that an
entrypoint may be a **file path**, because ADR 0152 §4's opt-in —
`aef migrate --agent-root .claude/agents`, and the only way a persona becomes
Zone A — writes `.claude/agents/migrated/<module>/graph.py`, and no dotted
spelling of that path exists at all (`.claude` is not an identifier, and a
leading dot means "relative import" to `importlib`).

It taught **one** of the three loaders. `aef/harness/scenario_runner.py` and
`aef/harness/node_worker.py` each kept their own `importlib.import_module`,
so under the documented opt-in:

    $ aef loop score '.claude/agents/migrated/reviewer/graph.py:build_graph' \\
        --corpus corpus --splits train --config aef.yaml
    error: the 'package' argument is required to perform a relative import
    for '.claude/agents/migrated/reviewer/graph.py'
    EXIT=1

— exit 1 is `EXIT_REJECTED` — and through `aef loop cycle` it is worse than a
refusal, because the two sides of G2 used **different** loaders: the incumbent
is reconstructed from the recording (which `aef loop record` could load,
because `aef loop record` goes through `aef run`'s importer), while the
candidate runs in `node_worker`, which could not. An import error on one side
only is indistinguishable, downstream, from a behavioural regression:

    G2 outcome : fail
    G2 reason  : 1 previously-passing scenario(s) no longer pass (zero tolerance)

So every prompt candidate is rejected forever on the flag that exists to
propose prompt candidates, and two rejections halt the loop.

This module is the fix's first half: one function, in the harness, because the
harness may not import the CLI (`aef/harness/zones.py` carries the same
argument for `DEFAULT_AGENT_PATH`). `aef/cli/run.py` imports it and re-exports
the two names it published, so `from aef.cli.run import import_graph_module`
keeps working and there is still only one implementation.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

__all__ = ["ensure_cwd_importable", "import_graph_module", "looks_like_a_path", "split_entrypoint"]


def ensure_cwd_importable() -> None:
    """`aef` runs as an installed console script, whose `sys.path[0]` is the
    script's own directory (e.g. `.venv/bin`), NOT the caller's current
    directory — unlike `python script.py` or `python -m`, where the CWD is on
    `sys.path` automatically. Without this, `aef run agents.foo.graph` can
    never find a module `aef init` just scaffolded one directory below where
    you are standing: confirmed by actually running `aef init` then `aef run`
    end-to-end, not inferred from reading the code."""
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)


def looks_like_a_path(module_path: str) -> bool:
    """Is this a FILE to load rather than a dotted module name to import?

    A `.py` suffix or a separator; nothing else. Deliberately not "try the
    import and fall back", because a dotted import that fails for its own
    reason — a typo inside the module, a missing dependency — would then be
    retried as a filename, miss, and be reported as "no such file", hiding the
    real error behind a second one.
    """
    return module_path.endswith(".py") or "/" in module_path or "\\" in module_path


def split_entrypoint(entrypoint: str) -> tuple[str, str]:
    """`'<module or file>:<factory>'` -> its two halves.

    A Windows drive letter is not a separator: `C:\\x\\graph.py:build_graph`
    splits on the LAST colon, and a bare `graph.py` (no factory) is an error
    rather than a module named `graph.py` with an empty attribute.
    """
    module_path, sep, attribute = entrypoint.rpartition(":")
    if not sep or not module_path or not attribute:
        raise ValueError(
            f"entrypoint must be '<module or file path>:<factory>', got {entrypoint!r}"
        )
    return module_path, attribute


def import_graph_module(module_path: str) -> ModuleType:
    """The one importer, for a dotted module name **or a file path**.

    The choice is made on the **spelling**, never by trying the import and
    falling back — see `looks_like_a_path`.

    `sys.modules` is keyed on a hash of the **resolved** path, because
    `aef migrate` names every generated file `graph.py`; the module is
    registered there before it is executed, which is what the import system
    does for a normal import and what a module importing itself (or a
    dataclass being pickled out of it) needs.
    """
    ensure_cwd_importable()
    if not looks_like_a_path(module_path):
        return importlib.import_module(module_path)

    path = Path(module_path)
    if not path.is_file():
        raise ValueError(
            f"{module_path!r} looks like a file path and there is no file there "
            f"(resolved to {path.resolve()}). Pass a dotted module name, or a path "
            f"to the .py file that defines build_graph()."
        )
    resolved = path.resolve()
    # Derived from the resolved path, so two graphs with the same basename in
    # different directories do not collide in `sys.modules` — `graph.py` is the
    # name `aef migrate` gives every single one of them.
    name = "aef_graph_" + hashlib.sha256(str(resolved).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:  # pragma: no cover - unreadable file
        raise ValueError(f"cannot load a Python module from {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
