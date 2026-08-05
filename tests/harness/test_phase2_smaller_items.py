"""Six items ADR 0074/0079/0080 recorded and deferred.

Each was reproduced by running before it was fixed. Grouped in one file
because they share nothing except having been written down and left (ADR
0084).
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# `extends` resolved nothing, silently
# --------------------------------------------------------------------------


_MINIMAL = """model_provider: {impl: anthropic, model: m, fallback: []}
memory: {impl: in_memory}
objectives: "x"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "aef.yaml"
    path.write_text(text)
    return path


def test_the_default_extends_still_loads(tmp_path: Path) -> None:
    from aef.config import load_agent_config

    assert load_agent_config(_write(tmp_path, "extends: _base\n" + _MINIMAL)).extends == "_base"


def test_a_non_default_extends_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    """Nothing resolves a base config — not a missing one, and not a present
    one either. The field accepted any string, so `extends: production-base`
    loaded clean and inherited nothing: an owner could believe a shared
    policy applied when no code had ever read it."""
    from aef.config import AgentConfigError, load_agent_config

    with pytest.raises(AgentConfigError, match="inheritance is not implemented"):
        load_agent_config(_write(tmp_path, "extends: production-base\n" + _MINIMAL))


# --------------------------------------------------------------------------
# The proposer and line endings / negative constants
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("RETRY = 3\r\nOTHER = 5\r\n", "RETRY = 4\r\nOTHER = 5\r\n"),
        ("RETRY = 3\nOTHER = 5\n", "RETRY = 4\nOTHER = 5\n"),
        ("RETRY = 3", "RETRY = 4"),
    ],
    ids=["crlf", "lf", "no-trailing-newline"],
)
def test_the_line_ending_survives_a_rewrite(source: str, expected: str) -> None:
    """A CRLF line was rewritten as LF, leaving one mixed ending in an
    otherwise-CRLF file — so the proposal was not the pure single-value edit
    its rationale described, and the artefact G0 scanned differed from the
    change that was reasoned about."""
    from aef.harness.proposer import find_constants, rewrite_constant

    constant = next(c for c in find_constants(source) if c.name == "RETRY")
    assert rewrite_constant(source, constant, 4) == expected


def test_negative_constants_are_reachable() -> None:
    """`X = -2` parses as UnaryOp(USub, Constant), not Constant, so every
    negative constant was invisible to `find_constants` while `_CONSTANT_RE`
    happily allowed `-?\\d+` — a dead regex branch, and an agent whose
    tunable was negative had nothing the proposer could reach."""
    from aef.harness.proposer import coerce_value, find_constants, rewrite_constant

    source = "OFFSET = -2\nOTHER = 5\n"
    found = {c.name: c for c in find_constants(source)}
    assert "OFFSET" in found
    assert found["OFFSET"].value == -2.0

    rewritten = rewrite_constant(source, found["OFFSET"], coerce_value(found["OFFSET"], -3))
    assert rewritten.startswith("OFFSET = -3")


# --------------------------------------------------------------------------
# The scaffold and `aef trace`
# --------------------------------------------------------------------------


def test_the_scaffolded_agent_emits_provenance() -> None:
    """The kernel never appends provenance — it arrives only from a
    StateDelta — so a graph that emits none replays empty under `aef trace`
    and scores `cost_tokens=0` under `aef eval`, which reads as a broken tool
    rather than an agent that reported nothing."""
    from aef.cli.init import _GRAPH_TEMPLATE
    from aef.kernel import GraphExecutor, Services
    from aef.state import AEFState

    namespace: dict[str, object] = {}
    exec(compile(_GRAPH_TEMPLATE.format(agent_name="demo"), "<scaffold>", "exec"), namespace)
    result = GraphExecutor(namespace["build_graph"]().compile(), Services()).run(  # type: ignore[operator]
        AEFState(run_id="r", agent_id="a", objective="o"), record_trace=True
    )
    assert result.final_state.provenance, "aef trace would print nothing"


# --------------------------------------------------------------------------
# bless and the gate must describe the same tree
# --------------------------------------------------------------------------


def test_bless_and_the_gate_share_one_agent_root() -> None:
    """`bless` took an `agent_root` and `_config` never set a `zone_policy`,
    so a non-default root gave G5's two inputs different trees — the ADR 0074
    defect, latent behind a default nobody had changed yet."""
    from aef.cli.loop import _config
    from aef.cli.main import build_parser

    parser = build_parser()
    gate = _config(
        parser.parse_args(
            [
                "loop",
                "gate",
                "--state",
                "/tmp/s",
                "--head",
                "x",
                "--workdir",
                "/tmp/w",
                "--agent-root",
                "srv/bots",
            ]
        )
    )
    bless = parser.parse_args(["loop", "bless", "--state", "/tmp/s", "--agent-root", "srv/bots"])
    assert gate.zone_policy.agent_root == bless.agent_root == "srv/bots"


def test_the_agent_root_default_is_unchanged() -> None:
    from aef.cli.loop import _config
    from aef.cli.main import build_parser

    args = build_parser().parse_args(
        ["loop", "gate", "--state", "/tmp/s", "--head", "x", "--workdir", "/tmp/w"]
    )
    assert _config(args).zone_policy.agent_root == "agents"


# --------------------------------------------------------------------------
# Rolling back two open merges
# --------------------------------------------------------------------------


def test_two_open_merges_unwind_to_the_baseline() -> None:
    """`archive.rollback(v)` APPENDS v's content as a new version, so
    reverting in ledger order made each rollback undo the previous one: with
    v2 and v3 both un-settled, reverting v2 restored the baseline and
    reverting v3 then restored v2 — reinstating the first regression, having
    reported both as rolled back.

    Reachable only with Tier-1 enabled, which is off. It is the only state in
    which the rollback machinery matters at all.
    """
    from aef.harness import archive

    root = Path(tempfile.mkdtemp())
    arch, dest = root / "archive", root / "tree"
    dest.mkdir()
    for content, note in (
        (b"MARKER='baseline'\n", "baseline"),
        (b"MARKER='regress-A'\n", "A"),
        (b"MARKER='regress-B'\n", "B"),
    ):
        archive.record(
            arch,
            "g",
            files={"agents/g.py": content},
            base_sha="0" * 40,
            head_sha="0" * 40,
            recorded_at=NOW,
            notes=note,
        )

    # Newest first, which is what the monitor now does.
    for version in (3, 2):
        archive.rollback(arch, "g", version - 1, dest, recorded_at=NOW, notes=f"revert v{version}")

    assert (dest / "agents" / "g.py").read_bytes() == b"MARKER='baseline'\n"


def test_the_monitor_reverts_newest_first() -> None:
    import inspect

    from aef.harness.loop import monitor

    assert "reverse=True" in inspect.getsource(monitor)
