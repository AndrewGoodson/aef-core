"""A1 — flip Tier-1 auto-merge on from config, env or flag.

Trust case §2, reported `held`. The attacker's goal is a `Decision` whose
disposition is `AUTO_MERGE`: that is the only value that puts agent-authored
code on main with no human in the path.

The exploit is not "call `decide(..., tier1_enabled=True)`" — that parameter
exists so the merge path is reachable in a test. The exploit is finding
anything in `aef/` that PASSES True: a config key, an environment read, a CLI
flag. That is what is attacked here, and the mutation proves the search would
notice one if it appeared.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from aef.harness.gates.base import GateOutcome, GateResult, PipelineResult
from aef.harness.review import Decision, Disposition, decide

REPO_ROOT = Path(__file__).resolve().parents[2]

# Anything that would hand `decide` a True, with whitespace squeezed out so
# `tier1_enabled = True` and `tier1_enabled=True` are the same finding.
_ENABLED = re.compile(r"tier1_enabled\s*=\s*True|tier1_auto_merge\s*=\s*True")


def _passing() -> PipelineResult:
    return PipelineResult(
        results=tuple(
            GateResult(gate=g, outcome=GateOutcome.PASS, reason="ok")
            for g in ("G0", "G1", "G4", "G5", "G2", "G3")
        )
    )


def _sources() -> dict[Path, str]:
    """Every shipped Python file, whitespace-normalised per line."""
    out: dict[Path, str] = {}
    for path in sorted((REPO_ROOT / "aef").rglob("*.py")):
        out[path] = path.read_text(encoding="utf-8")
    return out


def _search(sources: dict[Path, str], *, root: Path = REPO_ROOT) -> list[str]:
    hits: list[str] = []
    for path, text in sources.items():
        for number, line in enumerate(text.splitlines(), start=1):
            if _ENABLED.search(line):
                name = path.relative_to(root) if path.is_relative_to(root) else path
                hits.append(f"{name}:{number}: {line.strip()}")
    return hits


# --------------------------------------------------------------------------
# The attack
# --------------------------------------------------------------------------


def test_a1_no_shipped_code_path_turns_tier1_on() -> None:
    """The attack: reach `AUTO_MERGE` through configuration rather than
    through the source. There must be no line in `aef/` that supplies True."""
    hits = _search(_sources())
    assert hits == [], f"Tier-1 auto-merge is enabled somewhere in aef/: {hits}"


def test_a1_a_fully_passing_candidate_still_escalates() -> None:
    """And the behaviour, not only the absence. A candidate that clears every
    gate — the best case the attacker can construct without touching the
    gates at all — is escalated to a human."""
    decision = decide(_passing(), tier1_enabled=False)
    assert decision.disposition is Disposition.ESCALATE
    assert "not enabled" in decision.reason


def test_a1_the_yaml_schema_has_no_key_that_could_set_it() -> None:
    """The config surface is the attacker's cheapest route: a key that loads
    is a key someone can write. `aef.yaml` must not have one."""
    from aef.config.schema import AgentConfig, GatesConfig

    fields = set(AgentConfig.model_fields) | set(GatesConfig.model_fields)
    offenders = [f for f in fields if "tier" in f.lower() or "auto_merge" in f.lower()]
    assert offenders == [], f"aef.yaml exposes {offenders}, which would enable Tier-1 from config"


# --------------------------------------------------------------------------
# The mutation — the control removed
# --------------------------------------------------------------------------


def test_a1_the_control_is_load_bearing(tmp_path: Path) -> None:
    """Two halves, because A1 has two controls.

    1. `tier1_enabled` really is the switch: passing True yields AUTO_MERGE.
       If it did not, the search above would be guarding a dead parameter.
    2. The search really would find a line that set it. A search that cannot
       fail is not evidence, and this one runs over a synthesised source tree
       so the real one is never edited.
    """
    merged = decide(_passing(), tier1_enabled=True)
    assert merged.disposition is Disposition.AUTO_MERGE, (
        "`tier1_enabled` no longer reaches AUTO_MERGE, so test_a1_no_shipped_code_path... "
        "is watching a parameter that does nothing"
    )
    assert isinstance(merged, Decision)

    planted = tmp_path / "cli" / "loop.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("config = LoopConfig(tier1_enabled=True)\n", encoding="utf-8")
    assert _search({planted: planted.read_text(encoding="utf-8")}), (
        "the search does not detect a planted `tier1_enabled=True`, so its silence over "
        "aef/ means nothing"
    )


def test_a1_the_grep_and_the_scan_agree(attack_log: list[str]) -> None:
    """The scan above reads files; the trust case's own test shells out to
    grep. Two searches for one fact drift (ADR 0091), so they are compared
    rather than trusted."""
    grep = subprocess.run(
        ["grep", "-rn", "tier1_enabled", "aef/"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    ).stdout.splitlines()
    grep_hits = [h for h in grep if _ENABLED.search(h)]
    attack_log.append(f"grep: {len(grep_hits)} enabling line(s); scan: {len(_search(_sources()))}")
    assert grep_hits == _search(_sources()) == [], attack_log
