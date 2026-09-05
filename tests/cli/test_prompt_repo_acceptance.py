"""M5 — the acceptance test for a **prompt-file** repo (ADR 0158).

`test_adoption_sequence.py::test_an_adopted_repo_gates_a_candidate_end_to_end`
is this file's model, and it answers a different question: an SDK-call-site
repo, whose candidate is a Python edit. Every eligible repo in
`UPGRADE_LOOP.md`'s 2026-09-04 survey had **zero** SDK call sites — their
agents are `.claude/agents/*.md` personas run by a coding harness — so that
test says nothing about the shape aef-core is actually asked to adopt.

This one drives the whole documented sequence through the real CLI, as
subprocesses, against a synthetic repo shaped like the `marlin` pilot (three
personas, one nested; an `AGENTS.md` the repo's own agents read; a CRLF
`.gitignore`; a `.codex/`):

    adopt -> migrate -> loop bootstrap --memory -> loop bless -> loop doctor
          -> loop cycle --proposer rule_based_prompt

and asserts, against `ledger.jsonl` rather than a CLI summary line, that a
candidate **whose diff is one `.md` under `.claude/agents`** was proposed and
that the gates reached a **verdict**. It does NOT assert which verdict: a test
demanding acceptance can be satisfied by weakening G3 (ADR 0139's rule, and
ADR 0170's fixture B is the same argument).

Two deliberate shapes in here, both of which are findings rather than
convenience, and both written up in ADR 0158:

* **The R1 workaround.** `aef migrate --agent-root .claude/agents` writes
  graphs at `.claude/agents/migrated/<name>/graph.py`, and only `aef run` /
  `aef loop record` can load that path (ADR 0168's `import_graph_module`).
  `scenario_runner.load_graph` and `node_worker.load_graph` — what
  `--entrypoint` feeds, so `loop score` and G2/G3 inside `cycle`/`gate` —
  still call `importlib.import_module`, and no dotted spelling of a
  `.claude/...` path exists. So this test migrates at the **default** root,
  where the module is dotted-importable, and runs the loop with
  `--agent-root .claude/agents`. The candidate edits the persona, which is
  Zone A under that root; the graph module is Zone C and unchanged, which is
  fine — only *changed* files must be Zone A.
* **`--cassette-miss fail`, and what that makes the verdict.** A changed
  prompt is a changed cassette key, so the candidate misses every recorded
  call and G2 rejects it. That is the changed-prompt-cannot-replay rule, not
  a judgement on the prompt, and `UPGRADE_LOOP.md`'s own rule says a prompt
  candidate is gated live or not at all. The live half below does that; the
  offline half stays on `fail` because CI holds no credential and must not
  want one.
* **What ADR 0181 changed here.** ADR 0158 found that *no* provider served a
  live cassette miss inside the gates: `impl: command` could not be rebuilt
  worker-side because only `{impl, model}` crossed the boundary (F-M5-2), and
  `impl: claude_code`, which could, answered `Not logged in` because the
  sandbox's environment allowlist has no `USER` (F-M5-3). Both were pinned
  here as strict xfails and both are now closed, so the two tests that
  carried them assert the fixes instead: the whole `model_provider` block
  crosses, and the login reaches the worker **only** where the repo set
  `gates.live_model_calls: true`. The default allowlist is unchanged — the
  live half's config opts in explicitly, and the offline half never does.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# The synthetic repo: marlin's shape, not marlin's content.
# --------------------------------------------------------------------------

PERSONAS: dict[str, tuple[str, str]] = {
    "harbor-accela": (
        "accela-agent.md",
        """You are the Harbor connector specialist for the Accela permitting system.

You answer questions about whether a jurisdiction's connector may be enabled,
and what preconditions must hold first.

## Preconditions
- Harbor-owned managed credentials must be provisioned for the jurisdiction.
- A verified watermark cursor with a source-justified grace period.
""",
    ),
    "harbor-source": (
        "source-agent.md",
        """You are the Harbor source-of-record analyst.

You reconcile records across upstream permit sources and report discrepancies.
""",
    ),
    # Nested on purpose: `discover_prompt_agents` recurses because the Claude
    # Code CLI does (ADR 0152 §2), and `detect_prompt_surface` globbed one
    # level until ADR 0172's R4. A flat fixture cannot see either.
    "harbor-reviewer": (
        "sub/reviewer-agent.md",
        """You are the Harbor code reviewer.

You review a diff and report defects, one per line.
""",
    ),
}

# H1/R2: the adopter's own prose QUOTES the bare markers, with house rules
# between them. Before ADR 0172 adopt matched the first bare pair anywhere and
# replaced everything inside it, deleting RULE 7.
AGENTS_MD = """# Harbor house rules

Our agents read this file, not CLAUDE.md.

## RULE 6 - never guess a jurisdiction

## How the scaffold marks its own section

`aef adopt` writes a delimited block. It opens with <!-- aef:begin -->
and closes with <!-- aef:end -->, and everything between those two
markers belongs to the generator.

## RULE 7 - always cite the source record id

## RULE 8 - a verdict line ends every runbook answer
"""

# H1/R1: CRLF. `read_text`/`write_text` translated every line and adopt
# reported "your bytes outside it are unchanged" on a diff that deleted them.
GITIGNORE = b"node_modules/\r\ndist/\r\n*.log\r\n"

# The stub harness, as configuration rather than a mock: a real provider
# (`aef.providers.command_provider`) running a real subprocess. `/bin/echo`
# with the `{system}` slot filled means the reply is the persona body plus the
# objective, so the persona reaches the model call through the same channel a
# real harness would use, and the whole offline half needs no credential.
# `isolation:` is the owner's assertion (ADR 0169) and is honest here: echo
# has no tools, one turn and no project context.
STUB_CONFIG = """extends: _base

model_provider:
  impl: command
  model: stub-echo
  fallback: []
  command:
    argv: ["/bin/echo", "{system}", "{prompt}"]
    system_argv: ["{system}"]
    isolation: [no_tools, single_turn, no_project_context]

memory:
  impl: in_memory

evaluator:
  suites: []

tools:
  allow: []

policies:
  require_hitl_above_risk: 0.0
  forbid: []

objectives: "Answer Harbor connector questions."

evolution:
  enabled: false
"""

# Two inputs carry the SAME owner check, so its signature recurs in two
# distinct runs and becomes a lesson (ADR 0110's two-run rule, reached through
# ADR 0174's check-derived failure memory). The check is honest rather than
# rigged: the objective is a plain domain question and the owner wants every
# answer to end with a machine-readable verdict line a runbook can parse.
BOOTSTRAP_INPUTS = [
    {
        "id": "harbor-clearwater",
        "objective": "May the Clearwater connector be enabled?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
    {
        "id": "harbor-pinellas",
        "objective": "May the Pinellas connector be enabled?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
    {
        "id": "harbor-preconditions",
        "objective": "What preconditions must hold before any connector is enabled?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "watermark"}],
    },
]

AGENT_ROOT = ".claude/agents"
PERSONA = ".claude/agents/accela-agent.md"
MODULE = "agents.migrated.harbor_accela.graph"
GRAPH_ID = "harbor-accela"
BUILD_COMMAND = "python -m compileall -q agents/migrated"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _aef(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aef.cli.main", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _build_prompt_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# harbor\n\nA permitting data pipeline.\n")
    (root / "AGENTS.md").write_bytes(AGENTS_MD.encode())
    (root / ".gitignore").write_bytes(GITIGNORE)
    (root / ".codex").mkdir(exist_ok=True)
    (root / ".codex" / "README.md").write_text("Codex reads AGENTS.md.\n")
    for name, (rel, body) in PERSONAS.items():
        persona = root / ".claude" / "agents" / rel
        persona.parent.mkdir(parents=True, exist_ok=True)
        persona.write_text(
            f"---\nname: {name}\ndescription: {name} persona\n"
            f"tools: Read, Write, Bash\n---\n\n{body}"
        )
    skill = root / ".claude" / "skills" / "harbor-runbook"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: harbor-runbook\ndescription: the ingest runbook\n---\n\nSteps.\n"
    )
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "harbor")


@pytest.fixture
def prompt_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "harbor"
    _build_prompt_repo(repo)
    return repo, tmp_path


def _ledger(state: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (state / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# The offline half — CI runs this. No credential, no model.
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_prompt_file_repo_goes_from_adopt_to_a_gated_prompt_candidate(
    prompt_repo: tuple[Path, Path],
) -> None:
    repo, tmp_path = prompt_repo
    state = tmp_path / "loop-state"
    before_agents = (repo / "AGENTS.md").read_bytes()
    before_gitignore = (repo / ".gitignore").read_bytes()

    # 1. adopt, into a repo that is ALREADY populated. Three properties, each
    #    of which was a defect before ADR 0172.
    adopt = _aef(repo, "adopt", "--dir", ".")
    assert adopt.returncode == 0, adopt.stderr
    assert "detected framework: prompt_files (3 agents" in adopt.stdout, adopt.stdout
    assert ".codex" in adopt.stdout.splitlines()[0], adopt.stdout

    after_agents = (repo / "AGENTS.md").read_bytes()
    # R1: the adopter's bytes survive verbatim, at offset 0.
    assert after_agents.startswith(before_agents), "AGENTS.md was rewritten, not appended to"
    # R2: the balanced BARE pair in the adopter's prose is inert, and the
    #     house rules it brackets are still there.
    assert after_agents.count(b"RULE 7") == 1
    assert after_agents.count(b"RULE 8") == 1
    assert b"<!-- aef:begin -->" in after_agents, "the quoted marker was rewritten"
    # D2: only a SIGNED pair is adopt's.
    assert b"<!-- aef:begin sha256=" in after_agents, after_agents[-400:]

    after_gitignore = (repo / ".gitignore").read_bytes()
    assert after_gitignore.startswith(before_gitignore)
    assert b"# aef:begin sha256=" in after_gitignore
    # The block adopt ADDED is rendered in the file's own line ending.
    assert b"__pycache__/\r\n" in after_gitignore, after_gitignore
    stat = subprocess.run(
        ["git", "-C", str(repo), "diff", "--numstat", "--", "AGENTS.md", ".gitignore"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in stat.splitlines():
        added, removed, _path = line.split("\t")
        assert removed == "0", f"adopt DELETED lines: {line}"

    # 2. migrate. At the DEFAULT root — see the module docstring, R1.
    migrate = _aef(repo, "migrate", "--dir", ".")
    assert migrate.returncode == 0, migrate.stderr
    assert "found 3 prompt agent(s) under .claude/agents" in migrate.stdout
    assert "wrote 3 prompt agent graph(s)" in migrate.stdout
    for name in PERSONAS:
        module_dir = name.replace("-", "_")
        assert (repo / "agents" / "migrated" / module_dir / "graph.py").is_file(), migrate.stdout
    # The nested persona was found, which a flat glob would have missed.
    assert ".claude/agents/sub/reviewer-agent.md" in migrate.stdout
    # Every run command the report prints must parse, and must be an `aef run`
    # of a target this CLI accepts. ADR 0168's M4 was a printed command that
    # could not run at all.
    printed = [
        line.strip()
        for line in migrate.stdout.splitlines()
        if line.strip().startswith("-> aef run ")
    ]
    assert len(printed) == 3, migrate.stdout
    for line in printed:
        argv = shlex.split(line[len("-> ") :])
        assert argv[:2] == ["aef", "run"], argv
        assert argv[2] == f"agents.migrated.{argv[2].split('.')[2]}.graph", argv
        assert "--config" in argv and "aef.yaml" in argv, argv

    # 3. The stub harness. This is the ONE substitution the offline half makes
    #    and it is a real provider running a real subprocess, not a mock.
    (repo / "aef.yaml").write_text(STUB_CONFIG)

    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(BOOTSTRAP_INPUTS))

    # 4. bootstrap. `--memory` is what turns a failed OWNER CHECK into failure
    #    memory (ADR 0174); without it the cycle says `no admissible failure
    #    memory` and proposes nothing. `--state`/`--no-loop-state` is required
    #    since ADR 0141 — silence may not mean "do not consult the kill
    #    switch".
    boot = _aef(
        repo,
        "loop",
        "bootstrap",
        MODULE,
        "--corpus",
        "corpus",
        "--inputs",
        str(inputs),
        "--state",
        str(state),
        "--memory",
        str(state / "memory.jsonl"),
        "--config",
        "aef.yaml",
    )
    assert boot.returncode == 0, boot.stderr
    assert "recorded 3 scenario(s) in the train split" in boot.stdout
    # The check fails without an error (ADR 0113), and the run is still WRONG.
    assert "2 failed an owner check" in boot.stdout, boot.stdout
    assert "check-derived FAILURE record" in boot.stdout, boot.stdout

    memory = [
        json.loads(line)
        for line in (state / "memory.jsonl").read_text().splitlines()
        if line.strip()
    ]
    failures = [r for r in memory if r["kind"] == "failure"]
    assert len(failures) == 2, memory
    # One signature, two distinct runs — the two-run rule (ADR 0110) is what
    # makes this a lesson rather than an episode.
    signatures = {tuple(r["content"]["failed_checks"]) for r in failures}  # type: ignore[index]
    assert signatures == {("check:working_memory.prompt_agent:contains",)}, failures
    assert len({r["run_id"] for r in failures}) == 2, failures

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted, migrated, bootstrapped")

    # 5. bless, under the WIDENED root, so the baseline is a baseline of the
    #    tree that contains the prompts (ADR 0147/0152) and records which tree
    #    that was (ADR 0167's F7).
    blessed = _aef(
        repo,
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-root",
        AGENT_ROOT,
        "--agent-path",
        PERSONA,
        "--graph-id",
        GRAPH_ID,
    )
    assert blessed.returncode == 0, blessed.stderr
    assert "baseline v1" in blessed.stdout

    entries = sorted((state / "archive" / GRAPH_ID).glob("v*/entry.json"))
    assert len(entries) == 1, entries
    entry = json.loads(entries[0].read_text())
    assert entry["agent_root"] == AGENT_ROOT, entry
    digests = entry["file_digests"]
    assert PERSONA in digests, sorted(digests)
    assert all(p.startswith(AGENT_ROOT) for p in digests), sorted(digests)

    # 6. doctor. Two obligations are green here and the rest are advisory.
    doctor = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-root",
        AGENT_ROOT,
        "--corpus",
        "corpus",
        "--agent-path",
        PERSONA,
        "--graph-id",
        GRAPH_ID,
    )
    assert "Loop readiness — 6 things you must supply" in doctor.stdout
    assert f"[OK] blessed baseline        1 archived version(s) of '{AGENT_ROOT}'" in doctor.stdout
    # ...and obligation 3 is GREEN on the persona path: seam R2 (`--agent-path`
    # meant the persona to the proposer and a Python graph to preflight) was
    # fixed by ADR 0178 an hour after this test pinned the defect — preflight
    # now resolves a persona to the graph migrate generated for it.
    assert "[OK] reflect node routed to" in doctor.stdout, doctor.stdout

    # 7. G1a: the same widened root with `--agent-path` left at its default is
    #    refused, rather than reporting on a tree the loop cannot touch.
    defaulted = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-root",
        AGENT_ROOT,
        "--corpus",
        "corpus",
    )
    from aef.cli.loop import EXIT_USAGE

    assert defaulted.returncode == EXIT_USAGE, (defaulted.returncode, defaulted.stderr)
    assert "is not inside '.claude/agents'" in defaulted.stderr, defaulted.stderr
    assert "It was left at its default" in defaulted.stderr, defaulted.stderr

    # 8. One cycle, with the proposer that edits a PROMPT.
    cycle = _aef(
        repo,
        "loop",
        "cycle",
        "--repo",
        ".",
        "--state",
        str(state),
        "--workdir",
        str(tmp_path / "work"),
        "--agent-root",
        AGENT_ROOT,
        "--agent-path",
        PERSONA,
        "--module",
        MODULE,
        "--entrypoint",
        f"{MODULE}:build_graph",
        "--corpus",
        "corpus",
        "--memory",
        str(state / "memory.jsonl"),
        "--config",
        "aef.yaml",
        "--cassette-miss",
        "fail",
        "--proposer",
        "rule_based_prompt",
        "--graph-id",
        GRAPH_ID,
        "--build-command",
        BUILD_COMMAND,
    )
    # 2 would mean halted; 3 a configuration error. 0 or 1 is a real verdict.
    assert cycle.returncode in (0, 1), (cycle.returncode, cycle.stdout, cycle.stderr)
    assert "proposed cycle-" in cycle.stdout, cycle.stdout
    assert "gated: " in cycle.stdout, cycle.stdout

    # 9. THE assertions, read from the ledger rather than the summary line.
    ledger = _ledger(state)
    kinds = [e["kind"] for e in ledger]
    assert kinds[0] == "blessed", kinds

    proposed = [e for e in ledger if e["kind"] == "proposed"]
    assert len(proposed) == 1, kinds
    paths = proposed[0]["detail"]["paths"]  # type: ignore[index]
    assert list(paths) == [PERSONA], paths
    assert str(proposed[0]["detail"]["head"]).startswith("loop/cycle-")  # type: ignore[index]
    assert proposed[0]["detail"]["base"] == "main"  # type: ignore[index]

    gated = [e for e in ledger if e["kind"] == "gated"]
    assert len(gated) == 1, kinds
    detail = gated[0]["detail"]
    evidence = str(detail["evidence"])  # type: ignore[index]
    assert "could not build evidence" not in evidence, evidence
    # ADR 0170's prose cohort was BUILT and EXECUTED: five placebo personas
    # beside the candidate and the incumbent, over all three scenarios. Before
    # ADR 0170 this line read "the candidate changed no Python file, so there
    # is nothing to mutate for a control cohort".
    assert "1 candidate + 1 incumbent + 5 random control(s)" in evidence, evidence
    assert "21 scenario execution(s)" in evidence, evidence
    assert f"3/3 gated scenario(s) recorded from graph '{GRAPH_ID}'" in evidence, evidence

    gates = {str(g["gate"]): g for g in detail["gates"]}  # type: ignore[index,union-attr]
    # G0 opened a non-Python file and SAID it did not scan it (ADR 0152 §5);
    # before that, "no static-safety violations" was a claim about a file the
    # gate had never read, on the ordinary case for a prompt repo.
    assert gates["G0"]["outcome"] == "pass", gates["G0"]
    assert "NOT statically scanned (not Python" in str(gates["G0"]["reason"]), gates["G0"]
    assert gates["G1"]["outcome"] == "pass", gates["G1"]
    assert gates["G4"]["outcome"] == "pass", gates["G4"]
    # G5 measured drift against a baseline of the SAME tree (ADR 0167's F7):
    # a mismatch charged the first candidate 1.000 of a 0.500 budget.
    assert gates["G5"]["outcome"] == "pass", gates["G5"]
    assert "from the blessed baseline" in str(gates["G5"]["reason"]), gates["G5"]

    # G2 REACHED A VERDICT. Before ADR 0170 it could not: G1 and G2 both
    # materialised `workdir/workspace` and G2 died on
    # `TrustBoundaryError: scratch destination ... must be empty`.
    assert "TrustBoundaryError" not in str(gates["G2"]["reason"]), gates["G2"]
    assert gates["G2"]["outcome"] in ("pass", "fail"), gates["G2"]

    # And a verdict was REACHED — not which one. Under `--cassette-miss fail`
    # the candidate's changed prompt is a changed cassette key, so it misses
    # every recorded call and G2 rejects: that is the changed-prompt-cannot-
    # replay rule showing up as a rejection, NOT a judgement of the lesson.
    # The live half is where a prompt candidate is actually scored, and
    # `UPGRADE_LOOP.md` says so in as many words.
    verdicts = [k for k in kinds if k in ("accepted", "rejected", "escalated")]
    assert len(verdicts) == 1, kinds

    # 10. ADR 0139's failure shape is gone: no step exited 0 having done
    #     nothing. The cycle journalled itself even though it rejected (ADR
    #     0165/0167's F6), and the journal says a proposal happened.
    cycles = [
        json.loads(line)
        for line in (state / "cycles.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(cycles) == 1, cycles
    assert cycles[0]["proposed"] is True, cycles[0]
    assert "Disposition." in str(cycles[0]["verdict"]), cycles[0]

    # The loop kept its work on a local branch and never touched main.
    branch = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main", branch
    heads = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "loop/*", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert len(heads) == 1, heads
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "main", heads[0]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert diff == [PERSONA], diff
    candidate = subprocess.run(
        ["git", "-C", str(repo), "show", f"{heads[0]}:{PERSONA}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # The bullet is computed from records and carries its provenance; no model
    # was asked (ADR 0157).
    assert "## Lessons (aef)" in candidate, candidate
    assert "<!-- aef sig=failure:check:" in candidate, candidate
    assert "runs=2 -->" in candidate, candidate


# --------------------------------------------------------------------------
# The findings this sequence hit, each pinned as a strict xfail so the day one
# is fixed, the suite says so rather than staying quietly green.
# --------------------------------------------------------------------------


# Was a strict xfail pinning seam R2; ADR 0178 (fix wave J2) closed it, so this
# is now the regression test for the persona → generated-graph resolution.
@pytest.mark.slow
def test_doctor_judges_the_graph_when_agent_path_names_the_persona(
    prompt_repo: tuple[Path, Path],
) -> None:
    repo, tmp_path = prompt_repo
    state = tmp_path / "loop-state"
    assert _aef(repo, "adopt", "--dir", ".").returncode == 0
    assert _aef(repo, "migrate", "--dir", ".").returncode == 0
    (repo / "aef.yaml").write_text(STUB_CONFIG)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "migrated")
    doctor = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-root",
        AGENT_ROOT,
        "--corpus",
        "corpus",
        "--agent-path",
        PERSONA,
    )
    assert "[OK] reflect node routed to" in doctor.stdout, doctor.stdout


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F-M5-1: obligation 6's every-graph scan (ADR 0168, G1b) is passed only when "
        "`--agent-path` was left at its default, and G1a (ADR 0167) refuses a defaulted "
        "`--agent-path` whenever `--agent-root` is non-default. Their intersection is "
        "every widened-root repo, so obligation 6 can never scan more than one graph "
        "on exactly the repo shape both fixes were written for"
    ),
)
@pytest.mark.slow
def test_obligation_six_scans_every_graph_under_a_widened_root(
    prompt_repo: tuple[Path, Path],
) -> None:
    repo, tmp_path = prompt_repo
    assert _aef(repo, "adopt", "--dir", ".").returncode == 0
    assert _aef(repo, "migrate", "--dir", ".", "--agent-root", AGENT_ROOT).returncode == 0
    (repo / "aef.yaml").write_text(STUB_CONFIG)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "migrated")

    from aef.harness.zones import discover_graph_files

    # The capability is there — this is not a discovery bug.
    assert len(discover_graph_files(repo, agent_root=AGENT_ROOT)) == 5

    doctor = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(tmp_path / "loop-state"),
        "--agent-root",
        AGENT_ROOT,
        "--corpus",
        "corpus",
    )
    assert "5 graphs scanned" in doctor.stdout, doctor.stdout


# Was a strict xfail pinning F-M5-2; ADR 0181 (fix wave K1) closed it, so this
# is now the regression test for the provider crossing the sandbox boundary.
def test_the_live_provider_spec_can_rebuild_the_credential_free_provider(
    tmp_path: Path,
) -> None:
    """The base ref's WHOLE `model_provider` block crosses, so `impl: command`
    — the one provider that needs no credential, and the one ADR 0154 points
    every new adopter at — is rebuilt worker-side with its argv template
    intact. While only `{impl, model}` crossed, the schema refused the result
    (correctly: there was no `command:` block) and every scenario in every
    cohort member failed as `worker refused configuration`, which
    `g2_outcome` reported only as `1 error(s)`."""
    from aef.config.factory import build_model_provider
    from aef.config.loader import load_agent_config
    from aef.config.schema import ModelProviderConfig
    from aef.providers.command_provider import CommandProvider

    config_path = tmp_path / "aef.yaml"
    config_path.write_text(STUB_CONFIG)
    agent_config = load_agent_config(config_path)
    # Exactly what `_live_provider_from_base_ref` puts on the wire, through the
    # JSON the framed protocol actually carries.
    spec = json.loads(json.dumps(agent_config.model_provider.model_dump(mode="json")))
    # ...and exactly what `node_worker._configure` does with it.
    provider = build_model_provider(ModelProviderConfig.model_validate(spec))
    assert isinstance(provider, CommandProvider)
    assert spec["command"]["argv"] == ["/bin/echo", "{system}", "{prompt}"]


# Was a strict xfail pinning F-M5-3; ADR 0181 (fix wave K1) closed it — as a
# decision rather than a one-word patch, which is what M5 asked for.
def test_the_sandbox_env_allowlist_carries_what_the_harness_login_needs() -> None:
    """The login reaches the gate's worker, and ONLY where the repo asked.

    Measured (ADR 0181, the exact argv `ClaudeCodeProvider` builds): the
    allowlist alone -> `is_error: true, 'Not logged in'`; with `LOGNAME` ->
    still `Not logged in`; with `USER` -> `is_error: false, 'OK'`; and
    `PATH + USER` alone is enough, so it is not `HOME` either.

    The default allowlist is UNCHANGED and this test says so: it exists so no
    credential is inherited by the one process that runs candidate code, and
    a fix that widened it globally would let every gate pass on every repo
    spend the operator's quota. `gates.live_model_calls: true` is how an
    owner asks for the widening, per repo, in writing."""
    from aef.harness.sandbox import (
        DEFAULT_ENV_ALLOWLIST,
        HARNESS_LOGIN_ENV,
        NetworkPolicy,
        SandboxPolicy,
        with_harness_login,
    )

    assert "USER" not in DEFAULT_ENV_ALLOWLIST, sorted(DEFAULT_ENV_ALLOWLIST)
    assert HARNESS_LOGIN_ENV == frozenset({"USER"})
    widened = with_harness_login(SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED))
    assert "USER" in widened.env_allowlist


# M6 (ADR 0163) extends the sequence past `cycle` to the leg the trust case's
# criterion 1 actually names: a run recorded from production, harvested into
# the corpus. On the marlin pilot that leg promoted 0 of 5 real runs. Both
# causes are pinned here, offline, against the same synthetic repo and the same
# `command` stub — no credential, no model, and they fail loudly the day either
# is fixed.


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F-M6-1 and F-M6-2, in series. (1) `aef run --record-runs` constructs "
        "`RecordedRun(...)` with no `model_calls=`, so the field defaults to `()` and "
        "harvest's determinism re-check replays against an empty cassette — the exact "
        "failure `RecordedRun.model_calls`' own docstring calls 'a correct-looking "
        "rejection for the wrong reason'. (2) Even with the cassette supplied, "
        "`harvest._reexecution_services` builds `CassetteProvider(None, ...)` with no "
        "inner provider, so ADR 0169's `prompt_agent__containment` re-executes as "
        "`isolation: [], persona_role: 'unknown'` against the recorded values, and "
        "`_reexecutes_identically` compares the encoded trace byte for byte. So NO run "
        "of any `aef migrate`-generated prompt-agent graph is harvestable, on any repo"
    ),
)
@pytest.mark.slow
def test_a_recorded_production_run_can_be_harvested_into_the_corpus(
    prompt_repo: tuple[Path, Path],
) -> None:
    repo, tmp_path = prompt_repo
    runs = tmp_path / "runs"
    assert _aef(repo, "adopt", "--dir", ".").returncode == 0
    assert _aef(repo, "migrate", "--dir", ".").returncode == 0
    (repo / "aef.yaml").write_text(STUB_CONFIG)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "migrated")

    run = _aef(
        repo,
        "run",
        MODULE,
        "--objective",
        "May the Clearwater connector be enabled?",
        "--config",
        "aef.yaml",
        "--record-runs",
        str(runs),
    )
    assert run.returncode == 0, run.stderr
    recorded = sorted(runs.glob("*.json"))
    assert len(recorded) == 1, [p.name for p in recorded]

    harvest = _aef(
        repo,
        "loop",
        "harvest",
        MODULE,
        "--runs",
        str(runs),
        "--corpus",
        "corpus",
        "--state",
        str(tmp_path / "loop-state"),
        "--include-successes",
    )
    assert harvest.returncode == 0, harvest.stderr
    assert "promoted 1 run(s)" in harvest.stdout, harvest.stdout


def test_the_recorder_pins_the_cassette_the_determinism_check_needs() -> None:
    """F-M6-1, narrowed to the one line that causes it.

    `aef loop record` and `aef loop bootstrap` both go through `recorder.py`,
    which wraps the provider in a `CassetteProvider` and stores
    `recording.recorded` on the scenario. `aef run --record-runs` is the one
    recording path that does not — and it is the only one `harvest`, `cycle
    --runs` and the generated nightly workflow are fed from.

    This asserts what is TRUE TODAY, so it is a description rather than a pin,
    and the xfail above is what turns red when the defect is fixed. Its job is
    to make the cause greppable from the test suite.
    """
    import inspect

    from aef.cli import run as run_cli
    from aef.harness import recorder

    source = inspect.getsource(run_cli.run_graph_module)
    assert "RecordedRun(" in source
    assert "model_calls=" not in source, (
        "aef/cli/run.py now passes model_calls to RecordedRun — F-M6-1 may be fixed; "
        "check the strict xfail above."
    )
    assert "model_calls=recording.recorded" in inspect.getsource(recorder)


# --------------------------------------------------------------------------
# The live half — opt-in, against a clone of a real prompt-file repo.
# --------------------------------------------------------------------------

LIVE_CONFIG = """extends: _base

model_provider:
  impl: claude_code
  model: {model}
  fallback: []

memory:
  impl: in_memory

evaluator:
  suites: []

tools:
  allow: []

policies:
  require_hitl_above_risk: 0.0
  forbid: []

# The per-repo opt-in that makes `--cassette-miss live` legal (ADR 0181).
# Off by default everywhere; on here because this test IS the live gate pass,
# and with it the gate's worker inherits the operator's harness login — which
# is to say a candidate's code can spend the operator's quota. Stated in the
# config rather than passed as a flag on purpose: it is a property of the
# repo, not of one invocation.
gates:
  live_model_calls: true

objectives: "Answer Accela connector questions."

evolution:
  enabled: false
"""

# TWO inputs, both carrying the SAME owner check, and both asking for a short
# answer. Two is the minimum that makes a signature recur across distinct runs
# (ADR 0110), and it is also a budget decision: one gate pass costs
# `len(scenarios) x (1 candidate + 1 incumbent + 5 controls)` live calls, so a
# third scenario is +7. The check is the one ADR 0157 used and is honest — the
# objective is a plain domain question, and the owner wants a machine-readable
# verdict line the ingestion runbook can parse. The persona never says to emit
# one, and — measured — neither does the objective: the first attempt asked for
# "a machine-readable verdict line" in the prompt and the model duly wrote one
# for Clearwater, so the check passed and no failure recurred. Asking the
# question plainly is what makes the check a check.
LIVE_INPUTS = [
    {
        "id": "accela-clearwater",
        "objective": (
            "May the Accela connector be enabled for Clearwater? Answer in at most three sentences."
        ),
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
    {
        "id": "accela-pinellas",
        "objective": (
            "May the Accela connector be enabled for Pinellas County? Answer in at "
            "most three sentences."
        ),
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
]


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("AEF_LIVE_HARNESS") != "1",
    reason="live: spends real harness calls; set AEF_LIVE_HARNESS=1 and AEF_LIVE_PILOT",
)
def test_a_real_prompt_repo_gates_a_prompt_candidate_live(tmp_path: Path) -> None:
    """The same sequence on a COPY of a real prompt-file repo, live.

    `AEF_LIVE_PILOT` names a clone. It is copied first and the copy is what is
    written to — `UPGRADE_LOOP.md`'s rule is that nothing outside `aef-core`
    is ever written to, and a read-only clone is not an exception to it.

    Cost: 1 preflight (outside this test) + 3 recording calls + one gate pass
    of `len(scenarios) x (1 candidate + 1 incumbent + cohort_size controls)`.
    """
    pilot = os.environ.get("AEF_LIVE_PILOT")
    assert pilot, "set AEF_LIVE_PILOT to a clone of a prompt-file repo"
    model = os.environ.get("AEF_LIVE_MODEL", "claude-opus-5")

    repo = tmp_path / "pilot"
    # The clone is READ-ONLY: everything below writes to this copy. The
    # ignored directories are the clone's own git-ignored build output, so the
    # copy and the clone are identical as far as git — and therefore every
    # gate — is concerned.
    shutil.copytree(
        pilot,
        repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            "node_modules", "test-results", "playwright-report", ".next", "dist"
        ),
    )
    state = tmp_path / "loop-state"

    adopt = _aef(repo, "adopt", "--dir", ".")
    assert adopt.returncode == 0, adopt.stderr
    assert "prompt_files" in adopt.stdout, adopt.stdout

    migrate = _aef(repo, "migrate", "--dir", ".")
    assert migrate.returncode == 0, migrate.stderr
    assert "prompt agent graph(s)" in migrate.stdout, migrate.stdout

    (repo / "aef.yaml").write_text(LIVE_CONFIG.format(model=model))
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(LIVE_INPUTS))

    live_module = os.environ.get("AEF_LIVE_MODULE", "agents.migrated.marlin_accela.graph")
    live_persona = os.environ.get("AEF_LIVE_PERSONA", ".claude/agents/accela-agent.md")
    live_graph_id = os.environ.get("AEF_LIVE_GRAPH_ID", "marlin-accela")

    boot = _aef(
        repo,
        "loop",
        "bootstrap",
        live_module,
        "--corpus",
        "corpus",
        "--inputs",
        str(inputs),
        "--state",
        str(state),
        "--memory",
        str(state / "memory.jsonl"),
        "--config",
        "aef.yaml",
    )
    assert boot.returncode == 0, boot.stderr
    assert "failed an owner check" in boot.stdout, boot.stdout
    memory = [
        json.loads(line)
        for line in (state / "memory.jsonl").read_text().splitlines()
        if line.strip()
    ]
    failures = [r for r in memory if r["kind"] == "failure"]
    assert len({r["run_id"] for r in failures}) >= 2, failures

    # The clone carries no committer identity of its own and this process has
    # none to inherit; set it on the COPY, never anywhere global.
    _git(repo, "config", "user.email", "loop@aef.local")
    _git(repo, "config", "user.name", "aef loop")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted, migrated, bootstrapped")

    blessed = _aef(
        repo,
        "loop",
        "bless",
        "--repo",
        ".",
        "--state",
        str(state),
        "--agent-root",
        AGENT_ROOT,
        "--agent-path",
        live_persona,
        "--graph-id",
        live_graph_id,
    )
    assert blessed.returncode == 0, blessed.stderr

    cycle = _aef(
        repo,
        "loop",
        "cycle",
        "--repo",
        ".",
        "--state",
        str(state),
        "--workdir",
        str(tmp_path / "work"),
        "--agent-root",
        AGENT_ROOT,
        "--agent-path",
        live_persona,
        "--module",
        live_module,
        "--entrypoint",
        f"{live_module}:build_graph",
        "--corpus",
        "corpus",
        "--memory",
        str(state / "memory.jsonl"),
        "--config",
        "aef.yaml",
        # LIVE, on purpose: a changed prompt is a changed cassette key, so the
        # only honest way to score one is to make the call. This is the
        # measurement ADR 0158 could not make — its F-M5-3 meant the call did
        # not survive the gate's sandbox (`Not logged in`) and its F-M5-2
        # meant no credential-free provider could cross either, so G2's
        # rejection was an artifact of the environment rather than a
        # judgement of the prompt. Both closed in ADR 0181, and the assertions
        # below check that the executions really happened rather than trusting
        # the exit code.
        "--cassette-miss",
        "live",
        "--proposer",
        "rule_based_prompt",
        "--graph-id",
        live_graph_id,
        "--build-command",
        BUILD_COMMAND,
    )
    assert cycle.returncode in (0, 1), (cycle.returncode, cycle.stdout, cycle.stderr)

    ledger = _ledger(state)
    kinds = [e["kind"] for e in ledger]
    proposed = [e for e in ledger if e["kind"] == "proposed"]
    assert len(proposed) == 1, kinds
    assert list(proposed[0]["detail"]["paths"]) == [live_persona]  # type: ignore[index]

    gated = [e for e in ledger if e["kind"] == "gated"]
    assert len(gated) == 1, kinds
    detail = gated[0]["detail"]
    gates = {str(g["gate"]): g for g in detail["gates"]}  # type: ignore[index,union-attr]
    assert "G2" in gates, gates
    # The candidates ran under the operator's own harness login, and the
    # ledger says so — ADR 0181's audit-trail half.
    assert detail["live_model_calls"] is True, detail  # type: ignore[index]
    # And they really EXECUTED. `IsolationError: worker refused configuration`
    # (F-M5-2) and `ModelProviderError: claude exited 1 ... Not logged in`
    # (F-M5-3) both reached G2 as an ordinary regression, so the exit code and
    # the verdict cannot distinguish a live gate pass from the two defects
    # that made one impossible. The evidence line counts real executions.
    assert "scenario execution(s)" in str(detail["evidence"]), detail  # type: ignore[index]
    for failure_text in ("worker refused configuration", "Not logged in"):
        assert failure_text not in cycle.stdout, cycle.stdout
    # A verdict was REACHED. Which one it is, is the measurement, and it is
    # recorded in ADR 0158 rather than demanded here.
    assert [k for k in kinds if k in ("accepted", "rejected", "escalated")], kinds

    # The excerpt ADR 0158 quotes. Printed rather than asserted, because the
    # numbers are the finding.
    print("\n--- LIVE cycle stdout ---")
    print(cycle.stdout)
    print("--- LIVE gated ledger entry ---")
    print("evidence:", detail["evidence"])  # type: ignore[index]
    for gate_id in ("G0", "G1", "G4", "G5", "G2", "G3"):
        if gate_id in gates:
            print(f"{gate_id} {gates[gate_id]['outcome']}  {gates[gate_id]['reason']}")
    print("grounded_in:", detail["grounded_in"])  # type: ignore[index]
    print("kinds:", kinds)
    print("--- LIVE candidate diff ---")
    print(
        subprocess.run(
            ["git", "-C", str(repo), "diff", "main", str(proposed[0]["detail"]["head"])],  # type: ignore[index]
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
