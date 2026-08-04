"""G1 — does the candidate build?

Runs, in the sandbox, against the **post-merge workspace** (base ref +
Zone A overlay, `workspace.py`): every configured build command must succeed.
The default set mirrors this repo's green bar minus the formatter, which
rejects on cosmetics rather than correctness.

Two things this gate deliberately does **not** do, both corrected from the
superseded spec after the three-reviewer audit (04 §1.9):

- **No reachability check.** Routing is chosen by node code, not authorised
  by edges: `_resolve_route` returns the `Route` the node supplied
  (`executor.py`). `END` therefore never appears in an `Edge`, so
  END-reachability is undecidable from the edge set — and node reachability
  produces false positives, because `fallback_node_id` targets bypass edge
  resolution entirely (ADR 0036), making a correctly-wired fallback-only node
  look like an orphan.
- **No graph loading of its own.** `Graph.compile()` runs as part of the
  candidate's own test suite, where it belongs.

The suite must pass **as of the candidate**, which is the point: an agent
cannot delete the test that fails, because the tests are Zone B and come from
the base ref.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aef.harness.gates.base import Gate, GateContext, GateOutcome, GateResult
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy, run_sandboxed
from aef.harness.workspace import build_candidate_workspace

DEFAULT_BUILD_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "mypy", "--strict", "aef"),
    ("python", "-m", "pytest", "-q"),
)


@dataclass(frozen=True)
class G1Builds(Gate):
    id: str = "G1"
    commands: tuple[tuple[str, ...], ...] = field(default_factory=lambda: DEFAULT_BUILD_COMMANDS)

    def run(self, ctx: GateContext) -> GateResult:
        workspace = build_candidate_workspace(
            ctx.repo, ctx.verdict.diff, ctx.workdir / "workspace", ctx.zone_policy
        )
        policy = ctx.sandbox_policy or SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED)

        evidence: list[str] = []
        for command in self.commands:
            result = run_sandboxed(command, workdir=workspace, policy=policy)
            label = " ".join(command)
            if result.ok:
                evidence.append(f"{label}: ok")
                continue

            detail = "timed out" if result.timed_out else f"exit {result.returncode}"
            tail = (result.stderr or result.stdout).strip().splitlines()[-20:]
            return GateResult(
                gate=self.id,
                outcome=GateOutcome.FAIL,
                reason=f"build command failed ({detail}): {label}",
                evidence=(*evidence, f"{label}: {detail}", *tail),
            )

        return GateResult(
            gate=self.id,
            outcome=GateOutcome.PASS,
            reason=f"{len(self.commands)} build command(s) succeeded against the merged workspace",
            evidence=tuple(evidence),
        )
