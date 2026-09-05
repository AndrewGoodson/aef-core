"""M8 — the acceptance sequence on a repo shaped like the SECOND real one.

`test_prompt_repo_acceptance.py` (M5, ADR 0158) proves the documented
sequence on a fixture shaped like `marlin`. One repo is one repo: every
assertion in it could be true because marlin happens to be shaped that way.
This file runs the same sequence against a fixture built from what was
actually observed on the *other two* prompt-file repos in `UPGRADE_LOOP.md`'s
survey — `keystone` (7 agents, 4 skills, `AGENTS.md`, `.codex`) and
`datamining` (13 agents, 6 skills, `AGENTS.md` + a `CLAUDE.md` **symlink**) —
with the full run of both recorded in ADR 0187.

**What is different here from the marlin fixture**, each one a shape that
existed in a real repo and in no test before this file:

* **The persona's `name:` is not its filename.** Every keystone persona is
  `<role>-agent.md` carrying `name: marlin-<role>`, so the generated module,
  the graph id and the file on disk are three different strings. The marlin
  fixture named `harbor-accela` in `accela-agent.md` but its other two
  personas matched, and nothing asserted the mismatch.
* **Frontmatter with no `tools:` key at all** (keystone) *and* frontmatter
  carrying `model:` (datamining, 12 of 13). `migrate` reports the keys it
  read and did not honour, and the set differs per persona — a fixture where
  every persona carries the same keys cannot see that.
* **A skills tree with `.md` files under a directory literally named
  `agents/`.** keystone's `verify-and-ship` skill ships a contract-lint
  corpus at `.claude/skills/verify-and-ship/fixtures/contract-lint/{positive,
  negative}/agents/*.md` plus two nested `SKILL.md` fixtures. Five persona-
  shaped files and two extra skills that must be counted as neither. This is
  the shape `discover_skills`'s one-level glob was written for (its docstring
  says `rglob` found ten instead of six on the pilot) — asserted here rather
  than described.
* **A `CLAUDE.md` that is a symlink to `AGENTS.md`** (datamining, tracked in
  git as a symlink blob). Adoption must not write through it: appending to
  both entry files would put two aef blocks in one file.
* **No nested persona.** The marlin fixture has one, deliberately; keystone
  has none, so the flat case is the one under test here.
* **An `AGENTS.md` that does not quote the markers**, so this file says
  nothing about ADR 0172's R2 and everything about the ordinary case.

The offline substitution is M5's and is configuration rather than a mock:
`model_provider.impl: command` with `argv: ["/bin/echo", "{system}",
"{prompt}"]`. A real `CommandProvider`, a real subprocess, no credential, and
the persona in the system channel. `--cassette-miss fail` therefore makes the
verdict G2-reject — a changed prompt is a changed cassette key — and, exactly
as in M5, this file asserts a verdict was **reached**, never which one.

The three tests at the bottom were strict xfails when this file landed: the
defects ADR 0187 found, each reproduced on a scratch repo carrying only the
shape under test. ADR 0189's fix wave turned all three into passing regression
tests, and added a fourth beside F-M8-3 for the ordinary two-entry-file repo.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# The synthetic repo: keystone's shape, keystone's content nowhere.
# --------------------------------------------------------------------------

# keystone's seven, and the property no fixture had before: the file stem
# (`<role>-agent`) and the persona `name:` (`harbor-<role>`) are different
# strings, so `agents/migrated/harbor_source/graph.py` is generated from
# `.claude/agents/source-agent.md`. Frontmatter is `name` + `description`
# only — keystone declares no `tools:` on any persona.
ROLES = (
    "source",
    "azure",
    "reviewer",
    "security",
    "orchestrator",
    "implementer",
    "bug-hunter",
)

PERSONA_BODY = """# Harbor {role} agent

- Work only in assigned repository paths and Harbor-owned data boundaries.
- Keep scheduled ingestion disabled until two manual runs reconcile source,
  fetched, lake, and published counts and live readback passes.
- Treat event dates as record data, never as an ingestion watermark.
- Watermarks must follow source publication order and require a non-zero,
  source-justified grace period.
- Return counts and evidence. Never publish, deploy, or invent credentials.
"""

# No marker quoting here on purpose — ADR 0172's R2 is the marlin fixture's
# job. This is the ordinary populated `AGENTS.md`: the file the repo's own
# agents read, with house rules adopt must not touch.
AGENTS_MD = """# Harbor agent rules

## Cloud boundary

- This repository may access only its own dedicated subscription.
- Run cloud CLI commands through `./infra/harbor-cli`. Never run bare ones.

## RULE 7 - always cite the source record id

## RULE 8 - a verdict line ends every runbook answer
"""

GITIGNORE = b"node_modules/\ntest-results/\nplaywright-report/\n.DS_Store\n"

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

objectives: "Answer Harbor source-boundary questions."

evolution:
  enabled: false
"""

# Two inputs carry the SAME owner check so its signature recurs in two
# distinct runs and becomes a lesson (ADR 0110's two-run rule via ADR 0174's
# check-derived failure memory). The third passes on a word the persona body
# actually contains, which under `/bin/echo` is the whole of the system
# channel — so it proves the persona reached the model call.
BOOTSTRAP_INPUTS = [
    {
        "id": "harbor-connectors",
        "objective": "May the county connectors be enabled?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
    {
        "id": "harbor-ingestion",
        "objective": "May scheduled ingestion be enabled?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "VERDICT:"}],
    },
    {
        "id": "harbor-watermark",
        "objective": "What must a watermark follow?",
        "checks": [{"path": "working_memory.prompt_agent", "op": "contains", "value": "watermark"}],
    },
]

AGENT_ROOT = ".claude/agents"
PERSONA = ".claude/agents/source-agent.md"
MODULE = "agents.migrated.harbor_source.graph"
GRAPH_ID = "harbor-source"
BUILD_COMMAND = "python -c pass"

# keystone: 7 personas, 4 skills of its own, `AGENTS.md`, `.codex/`.
EXPECTED_AGENTS = len(ROLES)
EXPECTED_SKILLS = 4


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _aef(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "aef.cli.main", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _build_second_repo(root: Path, *, branch: str = "main") -> None:
    """keystone's tree, plus datamining's `CLAUDE.md` symlink."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# harbor\n\nA permitting data pipeline.\n")
    (root / "AGENTS.md").write_bytes(AGENTS_MD.encode())
    (root / ".gitignore").write_bytes(GITIGNORE)
    (root / ".codex").mkdir(exist_ok=True)
    (root / ".codex" / "README.md").write_text("Project instructions live in ../AGENTS.md.\n")

    # datamining tracks `CLAUDE.md` as a symlink to `AGENTS.md`. Adoption must
    # skip it: appending to both entry files writes two blocks into one file.
    (root / "CLAUDE.md").symlink_to("AGENTS.md")

    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    for role in ROLES:
        (agents / f"{role}-agent.md").write_text(
            f"---\nname: harbor-{role}\n"
            f"description: Validates harbor {role} records without publishing.\n"
            f"---\n\n{PERSONA_BODY.format(role=role)}"
        )

    skills = root / ".claude" / "skills"
    for name in ("county-onboard", "harbor-cost-check", "mcp-contract-check"):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}\n---\n\nSteps.\n")

    # keystone's fourth skill and the reason this fixture exists: a
    # contract-lint corpus of persona-shaped `.md` files under a directory
    # named `agents/`, plus two nested `SKILL.md` fixtures. Neither may be
    # counted as a persona nor as a skill.
    vas = skills / "verify-and-ship"
    vas.mkdir(parents=True)
    (vas / "SKILL.md").write_text(
        "---\nname: verify-and-ship\ndescription: the pre-done checklist\n---\n\nSteps.\n"
    )
    (vas / "validate_agent_contracts.py").write_text("def main() -> None:\n    pass\n")
    for polarity, stems in (
        ("positive", ("fixture-agent",)),
        ("negative", ("missing-input", "missing-output", "missing-status-evidence")),
    ):
        d = vas / "fixtures" / "contract-lint" / polarity / "agents"
        d.mkdir(parents=True)
        for stem in stems:
            (d / f"{stem}.md").write_text(
                f"---\nname: {stem}\ndescription: a lint fixture, not a persona\n---\n\nBody.\n"
            )
        sd = vas / "fixtures" / "contract-lint" / polarity / "skills" / "fixture-skill"
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text(
            "---\nname: fixture-skill\ndescription: a lint fixture, not a skill\n---\n\nBody.\n"
        )

    # keystone ships hooks and a settings.json beside its personas; they are
    # neither, and adopt/migrate must leave them entirely alone.
    hooks = root / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "secret-guard.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / ".claude" / "settings.json").write_text('{"hooks": {}}\n')

    _git(root, "init", "-q", "-b", branch)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "harbor")


@pytest.fixture
def second_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "harbor"
    _build_second_repo(repo)
    return repo, tmp_path


def _ledger(state: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (state / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# The sequence. Offline, no credential, CI runs it.
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_a_keystone_shaped_repo_goes_from_adopt_to_a_gated_prompt_candidate(
    second_repo: tuple[Path, Path],
) -> None:
    repo, tmp_path = second_repo
    state = tmp_path / "loop-state"
    before_agents = (repo / "AGENTS.md").read_bytes()
    before_gitignore = (repo / ".gitignore").read_bytes()

    # 1. adopt, into a populated repo whose skills tree is full of files that
    #    look like personas and skills and are neither.
    adopt = _aef(repo, "adopt", "--dir", ".")
    assert adopt.returncode == 0, adopt.stderr
    detection = adopt.stdout.splitlines()[0]
    assert detection == (
        f"detected framework: prompt_files ({EXPECTED_AGENTS} agents, "
        f"{EXPECTED_SKILLS} skills, AGENTS.md, .codex)"
    ), detection

    # The symlinked entry file is skipped BY NAME rather than followed. Two
    # entry files resolving to one inode would otherwise take two blocks.
    assert "CLAUDE.md (a symlink, or under one" in adopt.stdout, adopt.stdout
    assert (repo / "CLAUDE.md").is_symlink(), "adopt replaced the symlink with a regular file"

    after_agents = (repo / "AGENTS.md").read_bytes()
    assert after_agents.startswith(before_agents), "AGENTS.md was rewritten, not appended to"
    assert after_agents.count(b"RULE 7") == 1
    assert after_agents.count(b"RULE 8") == 1
    assert after_agents.count(b"<!-- aef:begin sha256=") == 1, "two blocks in one file"
    # ...and the symlink still resolves to exactly those bytes, once.
    assert (repo / "CLAUDE.md").read_bytes() == after_agents

    after_gitignore = (repo / ".gitignore").read_bytes()
    assert after_gitignore.startswith(before_gitignore)
    assert b"# aef:begin sha256=" in after_gitignore
    stat = subprocess.run(
        ["git", "-C", str(repo), "diff", "--numstat", "--", "AGENTS.md", ".gitignore"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert stat.strip(), "adopt changed neither entry file"
    for line in stat.splitlines():
        added, removed, _path = line.split("\t")
        assert removed == "0", f"adopt DELETED lines: {line}"
        assert int(added) > 0, line

    # 2. migrate.
    migrate = _aef(repo, "migrate", "--dir", ".")
    assert migrate.returncode == 0, migrate.stderr
    assert f"found {EXPECTED_AGENTS} prompt agent(s) under {AGENT_ROOT}" in migrate.stdout
    assert f"wrote {EXPECTED_AGENTS} prompt agent graph(s)" in migrate.stdout

    # The name is not the filename: the module comes from `name:`, and the
    # persona it was read from is named beside it.
    for role in ROLES:
        module_dir = f"harbor_{role}".replace("-", "_")
        graph = repo / "agents" / "migrated" / module_dir / "graph.py"
        assert graph.is_file(), f"{module_dir} missing:\n{migrate.stdout}"
        assert f"harbor-{role}  (.claude/agents/{role}-agent.md)" in migrate.stdout, migrate.stdout
        assert f"graph_id='harbor-{role}'" in migrate.stdout

    # No persona carries `tools:`, so migrate reports no unhonoured key for
    # any of them. On datamining, where 12 of 13 carry `model:` as well, the
    # same line reads `model, tools` — see the dedicated test below.
    assert "frontmatter read and NOT honoured" not in migrate.stdout, migrate.stdout

    # THE keystone shape: five persona-shaped `.md` files under a directory
    # named `agents/`, inside a skill's own lint corpus. None is a persona.
    assert "fixture-agent" not in migrate.stdout, migrate.stdout
    assert "missing-input" not in migrate.stdout, migrate.stdout
    assert not (repo / "agents" / "migrated" / "fixture_agent").exists()
    # ...and the two nested `SKILL.md` fixtures are not skills either.
    listed_skills = [
        line.strip() for line in migrate.stdout.splitlines() if line.strip().startswith("SKILL ")
    ]
    assert not any("fixture-skill" in line for line in listed_skills), listed_skills
    # The adopter's four, plus aef's own, which is labelled as not theirs.
    assert len(listed_skills) == EXPECTED_SKILLS + 1, listed_skills
    assert sum("(aef's own — not yours)" in line for line in listed_skills) == 1, listed_skills

    printed = [
        line.strip()
        for line in migrate.stdout.splitlines()
        if line.strip().startswith("-> aef run ")
    ]
    assert len(printed) == EXPECTED_AGENTS, migrate.stdout
    for line in printed:
        argv = shlex.split(line[len("-> ") :])
        assert argv[:2] == ["aef", "run"], argv
        assert argv[2].startswith("agents.migrated.") and argv[2].endswith(".graph"), argv
        assert "--config" in argv and "aef.yaml" in argv, argv

    # 3. The stub harness — a real provider running a real subprocess.
    (repo / "aef.yaml").write_text(STUB_CONFIG)
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(BOOTSTRAP_INPUTS))

    # 4. bootstrap. `--memory` is what turns a failed owner check into failure
    #    memory (ADR 0174); without it the cycle proposes nothing.
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
    assert "2 failed an owner check" in boot.stdout, boot.stdout
    assert "check-derived FAILURE record" in boot.stdout, boot.stdout
    # The persona reached the model call: the passing check matches a word
    # that appears only in the persona body, never in the objective.
    assert "passed  harbor-watermark" in boot.stdout, boot.stdout

    memory = [
        json.loads(line)
        for line in (state / "memory.jsonl").read_text().splitlines()
        if line.strip()
    ]
    failures = [r for r in memory if r["kind"] == "failure"]
    assert len(failures) == 2, memory
    signatures = {tuple(r["content"]["failed_checks"]) for r in failures}  # type: ignore[index]
    assert signatures == {("check:working_memory.prompt_agent:contains",)}, failures
    assert len({r["run_id"] for r in failures}) == 2, failures

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted, migrated, bootstrapped")

    # 5. bless, under the widened root.
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
    # Seven personas under the root, and the baseline holds every one of them
    # — a baseline that did not record its own tree charged the first
    # candidate 1.000 of a 0.500 budget (ADR 0167's F7).
    assert len(digests) == EXPECTED_AGENTS, sorted(digests)

    # 6. doctor. All six obligations are printed; two are green.
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
    # ADR 0178: `--agent-path` naming the PERSONA resolves to the graph
    # `migrate` generated for it, and the generated module is the one for
    # `harbor-source` rather than the one whose filename matched.
    assert "[OK] reflect node routed to" in doctor.stdout, doctor.stdout
    assert "agents/migrated/harbor_source/graph.py" in doctor.stdout, doctor.stdout
    assert doctor.stdout.count("[OK]") + doctor.stdout.count("[--]") == 6, doctor.stdout

    # 7. One cycle, with the proposer that edits a PROMPT.
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
    # NOT the ADR 0139 shape, and not F-M8-1's either: a cycle that finds no
    # candidate prints this and exits 0, which on a repo whose default branch
    # is not `main` is what happens instead of a gate pass.
    assert "no candidate" not in cycle.stdout, cycle.stdout

    # 8. THE assertions, read from the ledger rather than the summary line.
    ledger = _ledger(state)
    kinds = [e["kind"] for e in ledger]
    assert kinds[0] == "blessed", kinds

    proposed = [e for e in ledger if e["kind"] == "proposed"]
    assert len(proposed) == 1, kinds
    assert list(proposed[0]["detail"]["paths"]) == [PERSONA]  # type: ignore[index]
    assert str(proposed[0]["detail"]["head"]).startswith("loop/cycle-")  # type: ignore[index]
    assert proposed[0]["detail"]["base"] == "main"  # type: ignore[index]

    gated = [e for e in ledger if e["kind"] == "gated"]
    assert len(gated) == 1, kinds
    detail = gated[0]["detail"]
    evidence = str(detail["evidence"])  # type: ignore[index]
    assert "could not build evidence" not in evidence, evidence
    # ADR 0170's prose cohort was built and EXECUTED against a prompt agent.
    assert "1 candidate + 1 incumbent + 5 random control(s)" in evidence, evidence
    assert "21 scenario execution(s)" in evidence, evidence
    assert f"3/3 gated scenario(s) recorded from graph '{GRAPH_ID}'" in evidence, evidence
    # Offline, and the ledger records that no live call was permitted (ADR 0181).
    assert detail["live_model_calls"] is False, detail  # type: ignore[index]

    gates = {str(g["gate"]): g for g in detail["gates"]}  # type: ignore[index,union-attr]
    assert gates["G0"]["outcome"] == "pass", gates["G0"]
    assert "NOT statically scanned (not Python" in str(gates["G0"]["reason"]), gates["G0"]
    assert gates["G1"]["outcome"] == "pass", gates["G1"]
    assert gates["G4"]["outcome"] == "pass", gates["G4"]
    assert gates["G5"]["outcome"] == "pass", gates["G5"]
    assert "from the blessed baseline" in str(gates["G5"]["reason"]), gates["G5"]
    assert "TrustBoundaryError" not in str(gates["G2"]["reason"]), gates["G2"]
    assert gates["G2"]["outcome"] in ("pass", "fail"), gates["G2"]

    # A verdict was REACHED — not which one. Under `--cassette-miss fail` the
    # candidate's changed prompt is a changed cassette key, so it misses every
    # recorded call and G2 rejects: the changed-prompt-cannot-replay rule
    # showing up as a rejection, NOT a judgement of the lesson.
    verdicts = [k for k in kinds if k in ("accepted", "rejected", "escalated")]
    assert len(verdicts) == 1, kinds

    # 9. No step exited 0 having done nothing.
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
    assert "## Lessons (aef)" in candidate, candidate
    assert "<!-- aef sig=failure:check:" in candidate, candidate
    assert "runs=2 -->" in candidate, candidate


@pytest.mark.slow
def test_a_persona_model_frontmatter_key_is_reported_as_not_honoured(tmp_path: Path) -> None:
    """datamining's shape: `model: opus` on 12 of 13 personas, `tools:` on all
    13, and one persona (`data-floor-lead`) with `tools:` and no `model:`.

    The keys are read and never obeyed — `model_provider.model` in `aef.yaml`
    decides — so `migrate` must SAY so per persona rather than drop them in
    silence, and the set it reports must differ where the frontmatter differs.
    """
    repo = tmp_path / "mining"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("## Development\n\nUse background mode.\n")
    agents = repo / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "publisher.md").write_text(
        "---\nname: publisher\ndescription: final stage\n"
        "tools: Read, Write, Bash\nmodel: haiku\n---\n\nCommit with provenance.\n"
    )
    (agents / "data-floor-lead.md").write_text(
        "---\nname: data-floor-lead\ndescription: orchestrator\n"
        "tools: Read, Grep, Glob, Bash, Agent, WebSearch\n---\n\nFan out one pipeline.\n"
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "mining")

    migrate = _aef(repo, "migrate", "--dir", ".")
    assert migrate.returncode == 0, migrate.stderr
    lines = migrate.stdout.splitlines()

    def keys_after(persona_name: str) -> str:
        start = next(i for i, ln in enumerate(lines) if f"AGENT    {persona_name} " in ln)
        block = lines[start : start + 6]
        reported = [ln for ln in block if "frontmatter read and NOT honoured" in ln]
        return reported[0].split(":", 1)[1].strip() if reported else ""

    assert keys_after("publisher") == "model, tools", migrate.stdout
    assert keys_after("data-floor-lead") == "tools", migrate.stdout


# --------------------------------------------------------------------------
# The findings, each reproduced on a scratch repo carrying only its shape.
# --------------------------------------------------------------------------


def _minimal_prompt_repo(root: Path, *, branch: str, skills: int = 1) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# house rules\n\nOur agents read this file.\n")
    (root / "README.md").write_text("# scratch\n")
    (root / ".gitignore").write_text("node_modules/\n")
    persona = root / ".claude" / "agents" / "one-agent.md"
    persona.parent.mkdir(parents=True)
    persona.write_text(
        "---\nname: one-agent\ndescription: the only persona\n---\n\n"
        "You answer questions about the harbor watermark cursor.\n"
    )
    for i in range(skills):
        d = root / ".claude" / "skills" / f"skill-{i}"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: skill-{i}\ndescription: s{i}\n---\n\nSteps.\n")
    _git(root, "init", "-q", "-b", branch)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")


@pytest.mark.slow
def test_a_repo_whose_default_branch_is_not_main_does_not_no_op_silently(
    tmp_path: Path,
) -> None:
    """F-M8-1, reproduced in ADR 0187 and closed in ADR 0189.

    The ONLY difference from the passing case is the branch name. `git init -b
    trunk`, then adopt → migrate → bootstrap → bless → doctor → cycle with
    `--base` left at its default. It used to print `no agent source at
    .claude/agents/one-agent.md in main: no candidate` and exit **0** — blaming
    a persona that is present, in a sentence a legitimate empty proposal also
    prints, on the exit code that means nothing was wrong.

    Two assertions, because the fix has two halves. The default must RESOLVE to
    the repository's own default branch, so the documented sequence reaches a
    verdict on a repo with no `main` at all; and a base ref that does not exist
    must be REFUSED by name on `EXIT_ERROR`, never reported as a missing file.
    """
    repo = tmp_path / "trunk-repo"
    _minimal_prompt_repo(repo, branch="trunk")
    state = tmp_path / "loop-state"

    assert _aef(repo, "adopt", "--dir", ".").returncode == 0
    assert _aef(repo, "migrate", "--dir", ".").returncode == 0
    (repo / "aef.yaml").write_text(STUB_CONFIG)

    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            [
                {
                    "id": f"s{i}",
                    "objective": objective,
                    "checks": [
                        {
                            "path": "working_memory.prompt_agent",
                            "op": "contains",
                            "value": "VERDICT:",
                        }
                    ],
                }
                for i, objective in enumerate(("May it be enabled?", "May it be disabled?"))
            ]
        )
    )
    boot = _aef(
        repo,
        "loop",
        "bootstrap",
        "agents.migrated.one_agent.graph",
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
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adopted")

    # `main` does not exist. Every step so far said nothing about that.
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "main"], capture_output=True
        ).returncode
        != 0
    )
    assert (
        _aef(
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
            ".claude/agents/one-agent.md",
            "--graph-id",
            "one-agent",
        ).returncode
        == 0
    )

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
        ".claude/agents/one-agent.md",
        "--module",
        "agents.migrated.one_agent.graph",
        "--entrypoint",
        "agents.migrated.one_agent.graph:build_graph",
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
        "one-agent",
        "--build-command",
        BUILD_COMMAND,
    )
    # HALF ONE: the default resolved to `trunk`, so the turn actually ran.
    # Not which verdict — under `--cassette-miss fail` a changed prompt is a
    # changed cassette key and G2 rejects, which is the replay-artefact rule
    # and not a judgement (ADR 0187). That it REACHED one is the assertion.
    assert "no agent source" not in cycle.stdout, cycle.stdout
    assert "no candidate" not in cycle.stdout, cycle.stdout
    assert cycle.returncode != 0, (cycle.returncode, cycle.stdout, cycle.stderr)
    kinds = [
        json.loads(line)["kind"]
        for line in (state / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert "proposed" in kinds and "gated" in kinds, kinds

    # HALF TWO: `main` named explicitly is a configuration error, refused by
    # name on EXIT_ERROR, listing the branches that do exist.
    from aef.harness.loop import EXIT_ERROR

    refused = _aef(
        repo,
        "loop",
        "doctor",
        "--repo",
        ".",
        "--state",
        str(state),
        "--corpus",
        "corpus",
        "--agent-root",
        AGENT_ROOT,
        "--agent-path",
        ".claude/agents/one-agent.md",
        "--graph-id",
        "one-agent",
        "--base",
        "main",
    )
    both = refused.stdout + refused.stderr
    assert refused.returncode == EXIT_ERROR, (refused.returncode, both)
    assert "base ref 'main' does not exist" in both, both
    assert "trunk" in both, "the refusal must list the branches that DO exist"
    assert "no agent source" not in both, both


@pytest.mark.slow
def test_migrates_skill_header_count_matches_its_own_listing(tmp_path: Path) -> None:
    """F-M8-2, reproduced in ADR 0187 and closed in ADR 0189.

    Two skills of the adopter's, then `adopt` writes its own
    `new-model-check/SKILL.md` as a third: `migrate` used to say `found 2
    skill(s)` over a three-row list, which is keystone's `found 4` over 5 and
    datamining's `found 6` over 7 in miniature. The header now counts the rows
    it heads and says how they split; ADR 0172's D4 subtotal survives inside
    the parenthetical, which is the number that does not move when adoption
    runs."""
    repo = tmp_path / "skills-repo"
    _minimal_prompt_repo(repo, branch="main", skills=2)
    assert _aef(repo, "adopt", "--dir", ".").returncode == 0
    out = _aef(repo, "migrate", "--dir", ".").stdout

    header = next(line for line in out.splitlines() if "skill(s) and did NOT migrate" in line)
    declared = int(header.strip().split()[1])
    listed = [line for line in out.splitlines() if line.strip().startswith("SKILL ")]
    assert declared == len(listed), f"header {header.strip()!r} over {len(listed)} rows"
    assert "(2 yours + 1 aef's own)" in header, header
    assert sum("(aef's own — not yours)" in line for line in listed) == 1, listed


@pytest.mark.slow
def test_the_checklist_does_not_point_at_a_claude_md_adopt_skipped(tmp_path: Path) -> None:
    """F-M8-3, reproduced in ADR 0187 and closed in ADR 0189.

    `CLAUDE.md` is a symlink to `README.md`, so adopt skips it and it carries
    no aef block — and step 1 still said `Read the generated CLAUDE.md in full
    before writing any code.` On datamining the link points at `AGENTS.md`,
    which did get the block, so it accidentally worked; here it does not.
    Step 1 now names the file adopt actually appended to."""
    repo = tmp_path / "symlink-repo"
    _minimal_prompt_repo(repo, branch="main")
    (repo / "CLAUDE.md").symlink_to("README.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "symlink")

    adopt = _aef(repo, "adopt", "--dir", ".")
    assert adopt.returncode == 0, adopt.stderr
    assert "CLAUDE.md (a symlink, or under one" in adopt.stdout, adopt.stdout
    assert "aef:begin" not in (repo / "CLAUDE.md").read_text()

    step_one = next(line for line in adopt.stdout.splitlines() if line.strip().startswith("1. "))
    assert "CLAUDE.md" not in step_one, step_one
    # Not merely silent about the skipped file — it names the one that DID get
    # the block, and that file really carries it.
    assert "AGENTS.md" in step_one, step_one
    assert "aef:begin" in (repo / "AGENTS.md").read_text()
    assert step_one.strip() == "1. Read the generated AGENTS.md in full before writing any code."


@pytest.mark.slow
def test_the_checklist_names_both_entry_files_when_adopt_wrote_both(tmp_path: Path) -> None:
    """The other half of F-M8-3's fix: on the ordinary repo, where `CLAUDE.md`
    is absent and `AGENTS.md` is present, adopt writes one and appends to the
    other and step 1 names both. A step that named only `CLAUDE.md` was right
    here by luck; this pins that it is right by derivation."""
    repo = tmp_path / "normal-repo"
    _minimal_prompt_repo(repo, branch="main")

    adopt = _aef(repo, "adopt", "--dir", ".")
    assert adopt.returncode == 0, adopt.stderr
    step_one = next(line for line in adopt.stdout.splitlines() if line.strip().startswith("1. "))
    assert "CLAUDE.md" in step_one and "AGENTS.md" in step_one, step_one
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert "aef:begin" in (repo / name).read_text(), name

    # And a SECOND adopt, where both are skipped as `already carries the
    # current aef block`: the files still carry the contract, so step 1 must
    # still name them rather than fall through to the no-entry-file wording.
    again = _aef(repo, "adopt", "--dir", ".")
    assert again.returncode == 0, again.stderr
    step_one = next(line for line in again.stdout.splitlines() if line.strip().startswith("1. "))
    assert "CLAUDE.md" in step_one and "AGENTS.md" in step_one, step_one
