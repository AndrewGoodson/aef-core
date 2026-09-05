"""The prose control cohort — G3's null hypothesis for a prompt (ADR 0170).

Reproduced first (`ControlCohortGenerator` on a markdown source):

    ProposalError: cannot build a control cohort for 'agents/persona.md': no
    module-level numeric constants to mutate, so there is no null hypothesis
    to draw from

and one layer up, in `CohortBuilder`:

    SuiteError: the candidate changed no Python file, so there is nothing to
    mutate for a control cohort and G3 has no null hypothesis to test against

so a prompt candidate could be rejected and never accepted (ADR 0157 defect
2; ADR 0139 requirement 2, re-measured in ADR 0148 as the COHORT's limit
rather than the proposer's).

What is asserted here is the control's honesty, not that it is easy to beat:
matched length, no shared content word, one line of difference from the
candidate, and a refusal for every shape it has no null for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aef.harness.candidate import inspect_candidate
from aef.harness.git import GitRepo
from aef.harness.prose_cohort import (
    NEUTRAL_VOCABULARY,
    ProseCohortError,
    ProseCohortLeakError,
    ProseControlCohortGenerator,
    _assert_no_leak,
    _lesson_text,
)
from aef.harness.sandbox import NetworkPolicy, SandboxPolicy
from aef.harness.suite import CohortBuilder, SuiteError

PATH = "agents/persona.md"
INCUMBENT = "# Persona\n\nAnswer the operator's question.\n"
BULLET = "- <!-- aef sig=failure:prompt_agent runs=2 --> the reply ended without a verdict line"
CANDIDATE = f"# Persona\n\nAnswer the operator's question.\n\n## Lessons (aef)\n\n{BULLET}\n"


def _cohort(size: int = 5, seed: int = 0, **kw: object) -> tuple:  # type: ignore[type-arg]
    generator = ProseControlCohortGenerator(seed=seed, **kw)  # type: ignore[arg-type]
    return generator.generate(path=PATH, source=INCUMBENT, candidate=CANDIDATE, size=size)


def _added_line(member: str) -> str:
    """The one line that differs from the candidate."""
    a, b = CANDIDATE.splitlines(), member.splitlines()
    assert len(a) == len(b), "a control changed the file's shape, not just one bullet"
    differing = [y for x, y in zip(a, b, strict=True) if x != y]
    assert len(differing) == 1, differing
    return differing[0]


# --------------------------------------------------------------------------
# it is a cohort at all
# --------------------------------------------------------------------------


def test_a_markdown_candidate_now_has_a_cohort() -> None:
    """The defect, inverted: this call used to be unreachable because nothing
    could build a cohort for a file with no numeric constants."""
    assert len(_cohort()) == 5


def test_the_members_are_distinct_sources() -> None:
    """Five copies of one placebo is a point mass, not a distribution — G3's
    floor counts members and the percentile would be computed over nothing
    (the lesson ADR 0078 records for the numeric cohort)."""
    assert len({m.proposed for m in _cohort(size=5)}) == 5


def test_the_same_seed_and_candidate_reproduce_the_cohort() -> None:
    """A threshold nobody can re-derive cannot be audited."""
    assert [m.proposed for m in _cohort(seed=3)] == [m.proposed for m in _cohort(seed=3)]


def test_a_different_seed_draws_a_different_cohort() -> None:
    assert [m.proposed for m in _cohort(seed=3)] != [m.proposed for m in _cohort(seed=4)]


def test_every_member_is_ungrounded_by_design() -> None:
    """`Proposal.__post_init__` refuses an ungrounded non-control. A control
    that cited evidence would be a proposal, not a null."""
    for member in _cohort():
        assert member.is_control and member.grounded_in == () and member.rationale == ""


# --------------------------------------------------------------------------
# it is a CONTROL: one variable, matched length, no leaked content
# --------------------------------------------------------------------------


def test_a_control_differs_from_the_candidate_in_exactly_one_bullet() -> None:
    """The heading, the blank lines and the insertion point are the
    candidate's own, so the only variable between the two arms is the words."""
    for member in _cohort():
        assert _added_line(member.proposed).startswith("- <!-- aef sig=control-placebo")


def test_the_placebo_matches_the_treatment_s_token_count() -> None:
    """Length is matched in TOKENS — what a prompt is billed and attended in
    — and a mismatched bullet would confound the comparison with its size."""
    wanted = len(_lesson_text(BULLET).split())
    assert wanted > 0
    for member in _cohort():
        assert len(_lesson_text(_added_line(member.proposed)).split()) == wanted


def test_no_placebo_carries_a_content_word_of_the_real_lesson() -> None:
    """The property that makes this a null. ADR 0157's own caveat is the
    reason: the lesson that moved a scenario contained the literal string the
    owner's check looks for, so a placebo sharing its vocabulary would carry
    the treatment's active ingredient."""
    banned = {"reply", "ended", "without", "verdict", "line"}
    for member in _cohort():
        words = set(_lesson_text(_added_line(member.proposed)).lower().split())
        assert not (words & banned), words & banned


def test_a_placebo_carrying_the_lesson_is_refused_as_not_a_control() -> None:
    """The reward-hacking shape, checked rather than trusted."""
    with pytest.raises(ProseCohortLeakError, match="not a null hypothesis"):
        _assert_no_leak("the reply ended without a verdict line", "the verdict line was absent")


def test_a_leak_check_over_stopwords_only_does_not_fire() -> None:
    """Stated rather than left to be discovered: the check binds on content
    words, so a lesson made of them is not protected by it."""
    _assert_no_leak("it was not the same", "and they had been there")


def test_a_vocabulary_made_of_the_lesson_s_own_words_is_refused() -> None:
    """The layer above the leak check: the pool is filtered against the
    treatment before anything is drawn, so a vocabulary that cannot supply an
    information-free bullet is a refusal, never a quiet redraw."""
    with pytest.raises(ProseCohortError, match="no information-free bullet"):
        _cohort(vocabulary=("reply", "ended", "verdict"))


# --------------------------------------------------------------------------
# every shape it has no null for is refused, not cohorted
# --------------------------------------------------------------------------


def test_a_python_path_is_refused() -> None:
    with pytest.raises(ProseCohortError, match="defined for .md"):
        ProseControlCohortGenerator().generate(
            path="agents/graph.py", source=INCUMBENT, candidate=CANDIDATE, size=5
        )


def test_a_candidate_that_rewrites_the_persona_is_refused() -> None:
    """There is no null hypothesis for an arbitrary prose rewrite, and
    inventing one would give G3 a threshold that means nothing."""
    rewritten = "# Persona\n\nAnswer in French.\n"
    with pytest.raises(ProseCohortError, match="no null hypothesis"):
        ProseControlCohortGenerator().generate(
            path=PATH, source=INCUMBENT, candidate=rewritten, size=5
        )


def test_a_candidate_that_deletes_an_owner_bullet_is_refused() -> None:
    """An eviction of a bullet THIS loop wrote is part of the append and is
    allowed; removing the owner's prose is a different change."""
    owned = f"{INCUMBENT}\n## Lessons (aef)\n\n- always cite the ordinance\n"
    candidate = f"{INCUMBENT}\n## Lessons (aef)\n\n{BULLET}\n"
    with pytest.raises(ProseCohortError, match="which this loop did not write"):
        ProseControlCohortGenerator().generate(path=PATH, source=owned, candidate=candidate, size=5)


def test_a_candidate_that_adds_two_bullets_is_refused() -> None:
    two = f"{CANDIDATE}{BULLET.replace('sig=failure:prompt_agent', 'sig=other')}\n"
    with pytest.raises(ProseCohortError, match="add exactly one bullet"):
        ProseControlCohortGenerator().generate(path=PATH, source=INCUMBENT, candidate=two, size=5)


def test_a_zero_size_cohort_is_refused() -> None:
    with pytest.raises(ProseCohortError, match="at least 1"):
        _cohort(size=0)


def test_the_neutral_vocabulary_carries_no_instruction() -> None:
    """A reader has to be able to verify by eye that the placebo says nothing.
    Every word is a single lowercase adjective or noun — no verb an agent
    could obey, no punctuation, no domain term."""
    for word in NEUTRAL_VOCABULARY:
        assert word.isalpha() and word.islower(), word
    assert len(set(NEUTRAL_VOCABULARY)) == len(NEUTRAL_VOCABULARY)


# --------------------------------------------------------------------------
# the join: CohortBuilder picks the right null for the candidate it has
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, files: dict[str, str], changed: dict[str, str]) -> tuple[GitRepo, str]:
    root = tmp_path / "repo"
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@test")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "incumbent")
    _git(root, "checkout", "-qb", "loop/c1")
    for path, text in changed.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "candidate")
    _git(root, "checkout", "-q", "main")
    return GitRepo(root=root), "loop/c1"


def _builder(repo: GitRepo) -> CohortBuilder:
    return CohortBuilder(
        repo=repo,
        entrypoint="agents.graph:build_graph",
        policy=SandboxPolicy(network=NetworkPolicy.ACKNOWLEDGED_UNISOLATED),
    )


def test_the_builder_makes_prose_controls_for_a_markdown_candidate(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {PATH: INCUMBENT}, {PATH: CANDIDATE})
    made = _builder(repo)._control_workspaces(
        inspect_candidate(repo, "main", head).diff, tmp_path / "work"
    )
    assert len(made) == 5
    for _, workspace in made:
        assert "verdict" not in (workspace / PATH).read_text().lower()


def test_a_python_candidate_still_gets_the_numeric_cohort(tmp_path: Path) -> None:
    """Unchanged behaviour, asserted so the new branch cannot capture it: a
    candidate touching both kinds is controlled by the older, better-measured
    numeric cohort."""
    repo, head = _repo(
        tmp_path,
        {"agents/graph.py": "RETRIES = 4\nTIMEOUT_S = 2.5\n", PATH: INCUMBENT},
        {"agents/graph.py": "RETRIES = 5\nTIMEOUT_S = 2.5\n", PATH: CANDIDATE},
    )
    made = _builder(repo)._control_workspaces(
        inspect_candidate(repo, "main", head).diff, tmp_path / "work"
    )
    assert all(label.startswith("control-0-") for label, _ in made), made


def test_a_candidate_with_neither_kind_still_refuses(tmp_path: Path) -> None:
    """G3 must keep refusing where there is no null. Absence of evidence is
    not evidence, and this is the message that says so."""
    repo, head = _repo(
        tmp_path, {"agents/notes.rst": "hello\n"}, {"agents/notes.rst": "hello there\n"}
    )
    with pytest.raises(SuiteError, match="no Python file and no prompt file"):
        _builder(repo)._control_workspaces(
            inspect_candidate(repo, "main", head).diff, tmp_path / "work"
        )


def test_a_new_prompt_file_has_no_incumbent_to_control_against(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {"agents/other.md": "x\n"}, {PATH: CANDIDATE})
    with pytest.raises(SuiteError, match="does not exist at the base ref"):
        _builder(repo)._control_workspaces(
            inspect_candidate(repo, "main", head).diff, tmp_path / "work"
        )
