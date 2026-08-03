"""`aef doctor` — sanity-check an AEF-adopted (or freshly-initialized)
repo's setup: Python version, presence of CLAUDE.md, and validity of every
`aef.yaml` it can find.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from aef.config import AgentConfigError, load_agent_config


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


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
    checks.append(DoctorCheck("claude_md_present", claude_md.exists(), str(claude_md)))

    config_candidates = sorted(
        {*target_dir.glob("aef.yaml"), *target_dir.glob("agents/*/aef.yaml")}
    )
    if not config_candidates:
        checks.append(
            DoctorCheck("agent_config", False, "no aef.yaml found — run `aef adopt` or `aef init`")
        )
    for path in config_candidates:
        try:
            load_agent_config(path)
        except AgentConfigError as exc:
            checks.append(DoctorCheck(f"agent_config:{path}", False, str(exc)))
        else:
            checks.append(DoctorCheck(f"agent_config:{path}", True, "valid"))

    return checks
