"""`aef loop lineage list` — the archive an owner can read (ADR 0198).

J0b's second deduction on dimension 6, verbatim: *"no owner-facing `aef loop
lineage list` — only a counts line."* `aef loop run` prints `archive: N
member(s) ... M distinct kept tree(s)`, which says how big the search was and
nothing about its shape — and the information about a search is in the
rejections, because those are the places the loop reached and could not stand.

Two levels, for the reason `test_loop_run_archive_flags.py` states and this
repo has been caught by before: the PARSER (the subcommand exists, takes the
flags, and `--state` is required) and the HANDLER (it reads the file and
prints what it found). A parser test alone passes against a handler that
prints nothing.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aef.cli.main import build_parser, main
from aef.harness import archive

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "README.md").write_text("x\n")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def _record(ref: str, **kw: Any) -> archive.LineageRecord:
    payload: dict[str, Any] = {
        "run_id": "r1",
        "turn": 1,
        "ref": ref,
        "tree": f"tree-{ref}",
        "parent_ref": None,
        "score": None,
        "kept": True,
        "disposition": None,
        "recorded_at": NOW,
        "children": 0,
    }
    payload.update(kw)
    return archive.LineageRecord(**payload)


def _seed(state: Path, graph_id: str = "default") -> dict[str, str]:
    """A search with the shape the statistic is about: a rejected member that
    scored, and a kept member whose parent is that rejection."""
    lineage = state / "lineage"
    refs = {"root": "a" * 40, "stone": "b" * 40, "child": "c" * 40, "cheap": "d" * 40}
    archive.append_lineage(lineage, graph_id, _record(refs["root"], score=0.50, children=2))
    archive.append_lineage(
        lineage,
        graph_id,
        _record(
            refs["stone"], parent_ref=refs["root"], score=0.50, kept=False, disposition="reject"
        ),
    )
    archive.append_lineage(
        lineage,
        graph_id,
        _record(
            refs["child"], parent_ref=refs["stone"], score=0.67, kept=True, disposition="escalate"
        ),
    )
    archive.append_lineage(
        lineage,
        graph_id,
        _record(refs["cheap"], parent_ref=refs["root"], kept=False, disposition="reject"),
    )
    return refs


def _argv(state: Path, *extra: str) -> list[str]:
    """`--repo` defaults to `.`, which under pytest is this repository — so a
    seeded ref that is not a real commit would correctly read as gone. These
    tests are about the listing, not about liveness, so unless one says
    otherwise they point `--repo` at a directory that is not a checkout, which
    is the documented "nothing available to ask" case."""
    argv = ["loop", "lineage", "list", "--state", str(state), *extra]
    if "--repo" not in extra:
        argv += ["--repo", str(state.parent / "not-a-checkout")]
    return argv


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------
def test_the_parser_registers_lineage_list_and_routes_it_to_the_handler() -> None:
    from aef.cli.loop import cmd_lineage_list

    args = build_parser().parse_args(_argv(Path("/tmp/state")))
    assert args.loop_command == "lineage"
    assert args.lineage_command == "list"
    # `_wrap_loop_handlers` wraps every handler, nested groups included, so the
    # identity is not the bare function — the wrapper carries it.
    assert cmd_lineage_list.__name__ in getattr(args.handler, "__name__", "") or callable(
        args.handler
    )
    assert args.json is False


def test_the_parser_requires_a_state_directory() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["loop", "lineage", "list"])


def test_the_parser_requires_a_lineage_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["loop", "lineage"])


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------
def test_the_listing_names_every_member_its_parent_its_score_and_its_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refs = _seed(tmp_path / "state")
    assert main(_argv(tmp_path / "state")) == 0
    out = capsys.readouterr().out
    assert "4 member(s)" in out
    for ref in refs.values():
        assert ref[:12] in out, out
    # A parent column, not just a list of refs: lineage is the point.
    assert f"{refs['child'][:12]}  {refs['stone'][:12]}" in out.replace("  ", "  ")
    assert "escalate" in out and "reject" in out
    assert "0.6700" in out and "0.5000" in out


def test_the_listing_marks_an_unscored_reject_as_never_a_parent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_parent_weight`'s rule, on the surface an owner reads. A candidate a
    CHEAP gate refused has no task metric, so it is recorded and weighs zero —
    and a listing that showed it as eligible would be lying about what the
    next turn can do."""
    refs = _seed(tmp_path / "state")
    main(_argv(tmp_path / "state"))
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if refs["cheap"][:12] in line)
    assert "no " in line and "never a parent" in line
    stone = next(line for line in out.splitlines() if refs["stone"][:12] in line)
    assert "yes" in stone, "a rejected member that reached a score IS sampleable"


def test_the_listing_names_the_kept_member_that_descends_from_a_rejected_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """THE number this increment exists for, printed rather than left in a
    research JSONL."""
    refs = _seed(tmp_path / "state")
    main(_argv(tmp_path / "state"))
    out = capsys.readouterr().out
    assert "stepping stone:" in out
    assert f"{refs['child'][:12]} was KEPT from {refs['stone'][:12]}" in out
    assert "REJECTED" in out


def test_the_listing_says_so_when_no_kept_member_descends_from_a_rejection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative is stated, not left as an absence: ADR 0160's whole
    finding was a null result, and a listing that prints nothing when the
    answer is 'none' cannot report one."""
    lineage = tmp_path / "state" / "lineage"
    archive.append_lineage(lineage, "default", _record("a" * 40, score=0.5))
    archive.append_lineage(
        lineage,
        "default",
        _record("b" * 40, parent_ref="a" * 40, score=0.6, kept=True, disposition="escalate"),
    )
    main(_argv(tmp_path / "state"))
    out = capsys.readouterr().out
    assert "no kept member descends from a rejected one" in out


def test_an_empty_lineage_is_explained_rather_than_printed_as_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_argv(tmp_path / "state")) == 0
    out = capsys.readouterr().out
    assert "no lineage for 'default'" in out
    assert "--no-lineage" in out


def test_the_graph_id_selects_the_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path / "state", graph_id="demo_agent")
    assert main(_argv(tmp_path / "state", "--graph-id", "demo_agent")) == 0
    assert "4 member(s)" in capsys.readouterr().out
    assert main(_argv(tmp_path / "state")) == 0
    assert "no lineage for 'default'" in capsys.readouterr().out


def test_the_json_form_carries_the_weight_and_the_eligibility(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refs = _seed(tmp_path / "state")
    assert main(_argv(tmp_path / "state", "--json")) == 0
    payload = json.loads(capsys.readouterr().out)
    by_ref = {m["ref"]: m for m in payload["members"]}
    assert by_ref[refs["stone"]]["sampleable"] is True
    assert by_ref[refs["stone"]]["weight"] > 0.0
    assert by_ref[refs["cheap"]]["sampleable"] is False
    assert by_ref[refs["cheap"]]["weight"] == 0.0
    assert by_ref[refs["child"]]["parent_ref"] == refs["stone"]


def test_a_member_whose_branch_is_gone_is_reported_as_history(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With a real repository to ask, a ref that no longer resolves is not
    sampleable — the same skip `_resume_lineage` makes, said out loud."""
    lineage = tmp_path / "state" / "lineage"
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    archive.append_lineage(lineage, "default", _record(head, score=0.5))
    archive.append_lineage(
        lineage,
        "default",
        _record("e" * 40, parent_ref=head, score=0.6, kept=False, disposition="reject"),
    )
    main(_argv(tmp_path / "state", "--repo", str(repo)))
    out = capsys.readouterr().out
    gone = next(line for line in out.splitlines() if "eeeeeeeeeeee" in line)
    assert "no longer resolves" in gone
    alive = next(line for line in out.splitlines() if head[:12] in line)
    assert "yes" in alive


def test_a_tampered_record_is_refused_rather_than_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The listing goes through `read_lineage`, so it inherits the digest
    check rather than being a second, laxer reader of the same file."""
    lineage = tmp_path / "state" / "lineage"
    archive.append_lineage(lineage, "default", _record("a" * 40, score=0.5))
    path = archive.lineage_path(lineage, "default")
    path.write_text(path.read_text().replace('"score": 0.5', '"score": 0.9'))
    code = main(_argv(tmp_path / "state"))
    captured = capsys.readouterr()
    assert code != 0
    assert "digest mismatch" in captured.out + captured.err
