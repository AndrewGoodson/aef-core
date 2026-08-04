"""`aef doctor` — sanity-check an AEF-adopted (or freshly-initialized)
repo's setup: Python version, presence of CLAUDE.md, and validity of every
`aef.yaml` it can find.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from aef.config import AgentConfig, AgentConfigError, load_agent_config


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


def run_doctor(target_dir: Path) -> list[DoctorCheck]:
    target_dir = target_dir.resolve()
    checks: list[DoctorCheck] = []

    checks.append(
        DoctorCheck(
            "python_version",
            sys.version_info >= (3, 11),
            f"{sys.version_info.major}.{sys.version_info.minor} (need >=3.11)",
        )
    )

    claude_md = target_dir / "CLAUDE.md"
    claude_md_detail = (
        str(claude_md)
        if claude_md.exists()
        else f"{claude_md} not found — run `aef adopt` to generate one for an existing repo, "
        f"or add your own if this is a fresh `aef init`-based project"
    )
    checks.append(DoctorCheck("claude_md_present", claude_md.exists(), claude_md_detail))

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
    if not config.objectives.strip():
        out.append(
            DoctorCheck(
                f"advisory:{path}:empty_objectives",
                False,
                "objectives is empty/whitespace — the agent has no stated purpose; fill it in",
                level="advisory",
            )
        )
    return out
