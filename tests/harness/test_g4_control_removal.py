"""A control removed is a control cleared.

ADR 0079 added a base-vs-head check to G4 and claimed it caught removal
"however it was turned off". An adversarial pass found three one-step
evasions and one false positive that HALTED the loop on a benign rename —
and the fix had shipped with no test at all, which is ADR 0078's own lesson
recurring one commit later (ADR 0080).

Every attack here was reproduced as an actual HITL bypass through a real
`GraphExecutor` before being encoded, and every benign case was reproduced
as a real halt.
"""

import pytest

from aef.harness.gates.g4_separation import scan_metadata, scan_weakened_controls

HEADER = "from aef.kernel import Edge, Graph, Node\n"
BASE = HEADER + 'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'


def _findings(head_body: str) -> int:
    head = HEADER + head_body + "\n"
    return len(scan_metadata("a.py", head)) + len(scan_weakened_controls("a.py", BASE, head))


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("deleted kwarg", 'E = Edge(from_node="a", to_node="deploy")'),
        (
            "explicit False",
            'E = Edge(from_node="a", to_node="deploy", requires_human_approval=False)',
        ),
        ("falsy zero", 'E = Edge(from_node="a", to_node="deploy", requires_human_approval=0)'),
        ("falsy list", 'E = Edge(from_node="a", to_node="deploy", requires_human_approval=[])'),
        (
            # `_resolve_route` takes the first matching edge by priority, so an
            # unguarded twin wins while the guarded edge sits there looking
            # reassuring. Recording only guarded edges could not see it: the
            # purely additive diff removed nothing.
            "shadowed by an unguarded twin",
            'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'
            'E2 = Edge(from_node="a", to_node="deploy")',
        ),
        (
            "guard hidden behind a condition",
            'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True,'
            " condition=lambda s: False)\n"
            'E2 = Edge(from_node="a", to_node="deploy")',
        ),
    ],
)
def test_every_way_of_turning_a_control_off_is_caught(name: str, body: str) -> None:
    assert _findings(body), f"{name} evaded G4"


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("unchanged", 'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)'),
        # Keying on (from, to) alone made this a security event, and a
        # security event HALTS the loop unconditionally — so a two-line
        # rename bricked the autonomous loop with a false accusation.
        (
            "node renamed, control kept",
            'E = Edge(from_node="a", to_node="ship", requires_human_approval=True)',
        ),
        ("edge removed entirely", 'E = Edge(from_node="a", to_node="other")'),
        (
            "unrelated edge added",
            'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'
            'E2 = Edge(from_node="a", to_node="log")',
        ),
    ],
)
def test_benign_changes_do_not_halt_the_loop(name: str, body: str) -> None:
    assert not _findings(body), f"{name} was reported as a security event"


def test_introducing_the_recovery_marker_is_an_owner_only_change() -> None:
    """`RECOVERED_KEY` relaxes the pass predicate (ADR 0076) and, unlike
    `policy_denied`, has no Zone B writer — the contract is "whatever agent
    code says". Reproduced: an identical broken candidate has
    `regressed=True` without the key and `regressed=False` with it, so one
    dict key erased a real G2 regression, and harvest stopped promoting the
    agent's own failures into the corpus that would hold it to them."""
    body = (
        'E = Edge(from_node="a", to_node="deploy", requires_human_approval=True)\n'
        'ERR = {"node_id": "w", "error": "x", "recovered": True}'
    )
    assert _findings(body)


def test_an_owner_blessed_agent_keeps_its_recovery_handling() -> None:
    """Judged base-vs-head, so this blocks INTRODUCING the marker. An agent
    the owner already blessed with recovery handling is unaffected —
    otherwise ADR 0076's feature would be unusable by the agents it exists
    for."""
    base = BASE + 'ERR = {"node_id": "w", "error": "x", "recovered": True}\n'
    head = base + "\nUNRELATED = 1\n"
    assert not scan_weakened_controls("a.py", base, head)


def test_a_moved_module_cannot_drop_a_control_on_the_way() -> None:
    """`raw_diff` uses `--no-renames`, so `git mv` arrives as delete + add.
    G4's per-file loop skipped deletions, so the base was never read for the
    old path and the new path had no base — the diff handed G4 exactly the
    evidence it needed and G4 discarded it. The comparison is now made across
    all touched paths at once, which makes a move indistinguishable from an
    edit, because that is what it is."""
    moved = HEADER + 'E = Edge(from_node="a", to_node="deploy")\n'
    assert scan_weakened_controls("(candidate)", BASE, moved)
