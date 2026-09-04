"""`aef doctor` — sanity-check an AEF-adopted (or freshly-initialized)
repo's setup: Python version, presence of CLAUDE.md, and validity of every
`aef.yaml` it can find.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from aef.cli.migrate import DEFAULT_MIGRATED_OUT, LEGACY_MIGRATED_OUT
from aef.config import AgentConfig, AgentConfigError, load_agent_config
from aef.harness.preflight import model_calls_are_visible
from aef.harness.zones import DEFAULT_AGENT_ROOT


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    # "error" checks fail the overall `aef doctor` (exit 1) when not ok;
    # "advisory" checks are warnings only — surfaced to the user but never
    # flipping the exit code, for semantically-degenerate-but-valid config
    # (review Finding 4) that pydantic can't judge intent on.
    level: str = "error"


def _adapter_check(adapter: Path) -> DoctorCheck:
    """Does `aef_adapter.py` at least parse and expose `build_graph`?

    Parsed, not imported: importing an adopter's shim would execute whatever
    their legacy entrypoint does at module scope, and a diagnostic must not
    have side effects. Parsing catches the case that shipped — a file that is
    not valid Python — without running anything.
    """
    try:
        source = adapter.read_text()
        tree = ast.parse(source, filename=str(adapter))
    except UnicodeDecodeError as exc:
        return DoctorCheck("adapter_importable", False, f"{adapter} is not UTF-8: {exc}")
    except SyntaxError as exc:
        return DoctorCheck("adapter_importable", False, f"{adapter} does not parse: {exc}")
    except OSError as exc:  # pragma: no cover - unreadable file
        return DoctorCheck("adapter_importable", False, f"{adapter} is unreadable: {exc}")

    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "build_graph" not in names:
        return DoctorCheck(
            "adapter_importable",
            False,
            f"{adapter} defines no top-level build_graph(); nothing can load it",
        )

    still_a_stub = "wire your existing entrypoint into this node" in source
    return DoctorCheck(
        "adapter_importable",
        not still_a_stub,
        f"{adapter} parses and defines build_graph()"
        + (" — still the generated stub, not wired yet" if still_a_stub else ""),
        level="advisory" if still_a_stub else "info",
    )


def _graph_entries(target_dir: Path, agent_path: str | None) -> list[str]:
    """Which files are "the configured graph" for the model-call advisory.

    Keyed on the graph, not on migrate's output file. The advisory was written
    against the fixture the K1 increment had in hand — an adopter who ran
    `aef migrate` — and migrate's output is the artefact of a *different*
    command. The documented adoption path is `aef adopt`, wire
    `aef_adapter.py`, write nodes under `<agent_root>/**`; a repo that followed
    it to the letter produced no migrated file at all, so the advisory could
    not fire for the only path the docs describe (reproduced, ADR 0141).

    An explicit `--agent-path` wins outright — it is the same flag
    `aef loop doctor` takes and it means the owner has said which file it is.
    Otherwise every entry the adoption contract names, that exists, is
    scanned: the adapter shim, migrate's output, and each
    `<agent_root>/*/graph.py` — which is what `--agent-path` defaults into.

    Every path here is derived from `DEFAULT_AGENT_ROOT` via
    `aef.cli.migrate`, so moving the agent root or migrate's default cannot
    leave this list naming a directory nothing writes to. `LEGACY_MIGRATED_OUT`
    is the one exception and is named as such: it is where migrate wrote
    before ADR 0143, and dropping it would silently stop discovering the graph
    in every repo migrated before that day.
    """
    if agent_path:
        return [agent_path]
    entries: list[str] = []
    for name in ("aef_adapter.py", DEFAULT_MIGRATED_OUT, LEGACY_MIGRATED_OUT):
        if (target_dir / name).is_file():
            entries.append(name)
    agents_root = target_dir / DEFAULT_AGENT_ROOT
    if agents_root.is_dir():
        for graph in sorted(agents_root.glob("*/graph.py")):
            relative = graph.relative_to(target_dir).as_posix()
            if relative not in entries:
                entries.append(relative)
    return entries


def run_doctor(target_dir: Path, *, agent_path: str | None = None) -> list[DoctorCheck]:
    target_dir = target_dir.resolve()
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "python_version",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor} (need >=3.11)",
        )
    )

    # An `aef init` project legitimately has no CLAUDE.md — `init` does not
    # write one. Hard-failing that left a pristine `aef init` repo at exit 1
    # with no fix but to hand-write the file, while AGENT_INTEGRATION.md says
    # "fix any [FAIL]". Advisory when the repo looks init-shaped, an error
    # when it looks adopted (ADR 0079).
    claude_md = target_dir / "CLAUDE.md"
    adapter = target_dir / "aef_adapter.py"
    adoption_markers = (
        target_dir / "AEF_MIGRATION_CHECKLIST.md",
        target_dir / "AGENT_INTEGRATION.md",
        target_dir / "AUTONOMY.md",
        target_dir / "LOOP.md",
    )
    looks_adopted = (
        adapter.exists()
        or adapter.is_symlink()
        or any(marker.exists() for marker in adoption_markers)
    )
    claude_md_detail = (
        str(claude_md)
        if claude_md.exists()
        else f"{claude_md} not found — run `aef adopt` to generate one for an existing repo, "
        f"or add your own if this is a fresh `aef init`-based project"
    )
    checks.append(
        DoctorCheck(
            "claude_md_present",
            claude_md.exists(),
            claude_md_detail,
            level="error" if looks_adopted else "advisory",
        )
    )

    # F4: `aef adopt` promises doctor "confirms the config and IMPORTS are
    # wired correctly" and doctor never imported anything — so a syntactically
    # invalid `aef_adapter.py` passed clean.
    if adapter.is_file():
        checks.append(_adapter_check(adapter))
    elif looks_adopted:
        checks.append(
            DoctorCheck(
                "adapter_present",
                False,
                f"{adapter} is not a file — restore it or rerun `aef adopt`",
            )
        )

    # ADR 0137. `aef doctor` reported this repo green: `aef migrate` had
    # wrapped a function that builds its own `anthropic.Anthropic()`, so the
    # model call reached no `Services.model_provider`, the recorder captured
    # no `RecordedCall`, and the gates could only replay it by calling the
    # vendor live or scoring it 0. Nothing anywhere said so.
    #
    # Advisory, not an error: `aef doctor` checks that a setup is coherent,
    # while readiness to be gated is `aef loop doctor`'s question. An adopter
    # who has not routed their calls yet is mid-migration, not broken.
    for entry in _graph_entries(target_dir, agent_path):
        visible, detail, fix = model_calls_are_visible(target_dir, entry)
        checks.append(
            DoctorCheck(
                f"model_calls_visible:{entry}",
                visible,
                detail
                + (
                    ""
                    if visible
                    else ". It bypasses the policy engine and the fallback chain, and the "
                    f"gates cannot replay a call the recorder never saw. fix: {fix}"
                ),
                level="info" if visible else "advisory",
            )
        )

    config_candidates = sorted(
        {*target_dir.glob("aef.yaml"), *target_dir.glob("agents/*/aef.yaml")}
    )
    if not config_candidates:
        checks.append(
            DoctorCheck("agent_config", False, "no aef.yaml found — run `aef adopt` or `aef init`")
        )
    for path in config_candidates:
        try:
            config = load_agent_config(path)
        except AgentConfigError as exc:
            checks.append(DoctorCheck(f"agent_config:{path}", False, str(exc)))
        else:
            checks.append(DoctorCheck(f"agent_config:{path}", True, "valid"))
            checks.extend(_config_advisories(path, config))

    return checks


def _config_advisories(path: Path, config: AgentConfig) -> list[DoctorCheck]:
    """Warnings for config that validates but is semantically degenerate —
    review Finding 4. Advisory level only: `aef doctor` stays exit-0 unless
    something is actually broken. Not schema rejections, because a user may
    genuinely want e.g. two same-vendor endpoints, which pydantic can't
    judge."""
    out: list[DoctorCheck] = []
    primary = config.model_provider.impl
    fallback = config.model_provider.fallback

    if primary in fallback:
        out.append(
            DoctorCheck(
                f"advisory:{path}:fallback_same_as_primary",
                False,
                f"model_provider.fallback lists the primary impl {primary!r} — a same-vendor "
                f"fallback fails identically on a vendor outage; consider a different provider",
                level="advisory",
            )
        )
    if len(fallback) != len(set(fallback)):
        dupes = sorted({impl for impl in fallback if fallback.count(impl) > 1})
        out.append(
            DoctorCheck(
                f"advisory:{path}:fallback_duplicates",
                False,
                f"model_provider.fallback has duplicate entries {dupes} — each is tried in "
                f"order, so duplicates add no resilience",
                level="advisory",
            )
        )
    # `.startswith("TODO")` as well as empty: `aef adopt` writes
    # `objectives: "TODO: describe this agent's objective..."`, which is
    # non-empty — so the check built to catch "the agent has no stated
    # purpose" could not see the one string that ships by default (ADR 0079).
    objectives = config.objectives.strip()
    if not objectives or objectives.upper().startswith("TODO"):
        out.append(
            DoctorCheck(
                f"advisory:{path}:empty_objectives",
                False,
                "objectives is empty or still the generated TODO — the agent has no stated "
                "purpose; fill it in",
                level="advisory",
            )
        )
    return out
