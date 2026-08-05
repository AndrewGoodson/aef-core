"""The proposer — built last, because every gate that constrains it now
exists.

Building a proposer earlier would mean running an unconstrained proposer,
which is the thing the whole design exists to prevent.

Two products, and the second is not an afterthought:

1. **Grounded proposals.** Every candidate cites the evidence that motivated
   it. An ungrounded proposal is **not emitted at all** — not emitted and
   rejected downstream, but never constructed. "I thought this might help"
   is not a reason a gate can weigh, and a proposer that can emit one will
   fill the queue with them.

2. **The null-hypothesis control cohort.** G3 refuses to run without it
   (ADR 0051), and it is generated *here* because a control cohort must use
   the same mutation machinery as the real proposal. A cohort drawn from a
   different distribution than the candidate tests nothing about the
   candidate.

**Grounding may cite the train split only.** Citing validation would let the
proposer optimise against the set that gates it; citing the holdout would
destroy the owner's only independent read. This is enforced, not documented
— `propose` raises on a citation outside train.

The cohort is deliberately **ungrounded and random**. That is what makes it
a null hypothesis: it is what "changes that were not reasoned about" score,
and the candidate has to beat it.
"""

from __future__ import annotations

import ast
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from aef.harness.corpus import Corpus, Split
from aef.services.memory.base import MemoryRecord, MemoryStore


class ProposalError(RuntimeError):
    pass


class UngroundedProposalError(ProposalError):
    """A proposal with no evidence behind it. Its own type because this is
    not a validation failure to report — it is a proposal that must never
    exist."""


class CitationKind(StrEnum):
    SCENARIO = "scenario"  # a train-split corpus scenario
    MEMORY = "memory"  # a failure/success record written by a reflect node


@dataclass(frozen=True)
class Citation:
    """One piece of evidence a proposal is grounded in.

    Two kinds, with different admissibility rules. A **scenario** citation
    must name the train split, checkable rather than merely asserted. A
    **memory** citation names a `MemoryRecord` written by a reflect node —
    the lessons an agent recorded about its own runs, which is what makes
    this loop self-*learning* rather than self-modifying (ADR 0065).

    Memory records carry no split of their own, so the leak they could cause
    is indirect: a reflect node running over a holdout scenario writes a
    record whose `run_id` is that scenario's id, and citing it would leak the
    holdout by proxy. `MemoryEvidence` filters those out at the source.
    """

    source: str
    split: Split | None = None
    detail: str = ""
    kind: CitationKind = CitationKind.SCENARIO

    def __str__(self) -> str:
        where = self.split.value if self.split is not None else self.kind.value
        return f"{self.source} ({where}){f': {self.detail}' if self.detail else ''}"


@dataclass(frozen=True)
class Proposal:
    id: str
    path: str
    original: str
    proposed: str
    rationale: str
    grounded_in: tuple[Citation, ...] = ()
    is_control: bool = False

    @property
    def is_noop(self) -> bool:
        return self.original == self.proposed

    def __post_init__(self) -> None:
        if self.is_noop:
            raise ProposalError(
                f"proposal {self.id!r} changes nothing; a no-op consumes a gate run and a "
                f"rate-budget slot to prove the system still works"
            )
        if not self.is_control and not self.grounded_in:
            # Control-cohort members are ungrounded BY DESIGN — that is what
            # makes them a null hypothesis. Real proposals are not.
            raise UngroundedProposalError(
                f"proposal {self.id!r} cites no evidence. A proposal a gate cannot trace to "
                f"a recorded failure or success is not a hypothesis, and 'it might help' is "
                f"not a reason any gate can weigh."
            )
        if not self.is_control and not self.rationale.strip():
            raise ProposalError(f"proposal {self.id!r} has no rationale")


# Module-level `NAME = <number>` — the smallest thing a rule-based proposer
# can change with a defensible story about what it did.
_CONSTANT_RE = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<value>-?\d+(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class NumericConstant:
    name: str
    value: float
    line: int
    is_int: bool


def find_constants(source: str) -> tuple[NumericConstant, ...]:
    """Module-level numeric constants, found by AST rather than by regex
    alone so a match inside a string or a nested scope cannot be rewritten."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()

    found: list[NumericConstant] = []
    for node in tree.body:  # module level only
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int | float):
            found.append(
                NumericConstant(
                    name=target.id,
                    value=float(value.value),
                    line=node.lineno,
                    is_int=isinstance(value.value, int),
                )
            )
    return tuple(found)


def rewrite_constant(source: str, constant: NumericConstant, new_value: float) -> str:
    """Replace one constant's value, matching only the assignment line."""
    lines = source.splitlines(keepends=True)
    index = constant.line - 1
    if index >= len(lines):  # pragma: no cover - line comes from the same parse
        raise ProposalError(f"constant {constant.name!r} is not on line {constant.line}")

    rendered = str(int(new_value)) if constant.is_int else repr(new_value)
    match = _CONSTANT_RE.match(lines[index].rstrip("\n"))
    if match is None or match.group("name") != constant.name:
        raise ProposalError(
            f"line {constant.line} does not look like an assignment of {constant.name!r}; "
            f"refusing to rewrite it"
        )
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"{constant.name} = {rendered}{ending}"
    return "".join(lines)


def coerce_value(constant: NumericConstant, new_value: float) -> float:
    """Snap a proposed value onto the constant's own type, moving it by at
    least one whole unit for integers.

    Truncating instead would make small integers silently un-proposable:
    `int(3 * 1.25)` is `3`, so a retry limit of 3 — exactly the kind of
    constant worth tuning — could never be changed at all. Found by a test,
    not anticipated.
    """
    if not constant.is_int:
        return new_value
    if new_value > constant.value:
        return float(max(int(new_value), int(constant.value) + 1))
    if new_value < constant.value:
        return float(min(int(new_value), int(constant.value) - 1))
    return constant.value


def _check_citations(citations: Sequence[Citation]) -> None:
    off_limits = [
        c for c in citations if c.kind is CitationKind.SCENARIO and c.split is not Split.TRAIN
    ]
    if off_limits:
        raise ProposalError(
            f"grounding may cite the train split only; got {[str(c) for c in off_limits]}. "
            f"Citing validation lets the proposer optimise against the set that gates it; "
            f"citing the holdout destroys the owner's only independent read."
        )
    mislabelled = [c for c in citations if c.kind is CitationKind.MEMORY and c.split is not None]
    if mislabelled:
        raise ProposalError(
            f"a memory citation carries no split; got {[str(c) for c in mislabelled]}. "
            f"Whether a memory record is admissible depends on the RUN that produced it, "
            f"which MemoryEvidence decides — a split on the citation would look like a "
            f"check while checking nothing."
        )


@dataclass(frozen=True)
class RuleBasedProposer:
    """Deterministic, evidence-first. Emits one proposal per constant it can
    justify changing, and nothing otherwise."""

    step: float = 0.25

    def propose_from_memory(
        self,
        evidence: MemoryEvidence,
        *,
        proposal_id: str,
        path: str,
        source: str,
    ) -> tuple[Proposal, ...]:
        """Propose from what the agent recorded about its own failures.

        The rationale is built from the recorded feedback rather than
        invented, so a reader can trace the proposal back to the run that
        motivated it. Empty evidence produces nothing — the proposer does not
        fall back to speculating when it has learned nothing.
        """
        citations = evidence.citations()
        if not citations:
            return ()
        summary = (
            "; ".join(str(c.detail) for c in citations[:3] if c.detail)
            or f"{len(citations)} recorded failure(s)"
        )
        return self.propose(
            proposal_id=proposal_id,
            path=path,
            source=source,
            citations=citations,
            rationale=f"grounded in recorded failures — {summary}",
        )

    def propose(
        self,
        *,
        proposal_id: str,
        path: str,
        source: str,
        citations: Sequence[Citation],
        rationale: str,
    ) -> tuple[Proposal, ...]:
        _check_citations(citations)
        if not citations:
            raise UngroundedProposalError(
                f"refusing to propose against {path!r} with no evidence — the proposer does "
                f"not speculate"
            )

        proposals: list[Proposal] = []
        for index, constant in enumerate(find_constants(source)):
            new_value = coerce_value(constant, constant.value * (1.0 + self.step))
            if new_value == constant.value:
                continue  # nothing to say about this one
            proposals.append(
                Proposal(
                    id=f"{proposal_id}-{index}",
                    path=path,
                    original=source,
                    proposed=rewrite_constant(source, constant, new_value),
                    rationale=(
                        f"{rationale} — raising {constant.name} from {constant.value:g} to "
                        f"{new_value:g}"
                    ),
                    grounded_in=tuple(citations),
                )
            )
        return tuple(proposals)


@dataclass(frozen=True)
class ControlCohortGenerator:
    """Random mutations, using the *same* machinery as a real proposal.

    A cohort drawn from a different distribution than the candidate tests
    nothing about the candidate — so this deliberately reuses
    `find_constants`/`rewrite_constant` rather than perturbing text.

    Seeded, because a control cohort that cannot be reproduced cannot be
    audited: the whole point is that someone can re-derive the threshold a
    candidate was measured against.
    """

    seed: int = 0
    scale: tuple[float, float] = (0.5, 2.0)

    def generate(self, *, path: str, source: str, size: int) -> tuple[Proposal, ...]:
        if size < 1:
            raise ProposalError(f"control cohort size must be at least 1, got {size}")
        constants = find_constants(source)
        if not constants:
            raise ProposalError(
                f"cannot build a control cohort for {path!r}: no module-level numeric "
                f"constants to mutate, so there is no null hypothesis to draw from"
            )

        rng = random.Random(self.seed)
        cohort: list[Proposal] = []
        attempts = 0
        while len(cohort) < size and attempts < size * 20:
            attempts += 1
            constant = rng.choice(constants)
            factor = rng.uniform(*self.scale)
            new_value = coerce_value(constant, constant.value * factor)
            if new_value == constant.value:
                continue
            cohort.append(
                Proposal(
                    id=f"control-{self.seed}-{len(cohort)}",
                    path=path,
                    original=source,
                    proposed=rewrite_constant(source, constant, new_value),
                    rationale="",
                    grounded_in=(),
                    is_control=True,  # ungrounded BY DESIGN — that is the null hypothesis
                )
            )

        if len(cohort) < size:
            raise ProposalError(
                f"could only generate {len(cohort)} of {size} control mutations for {path!r}; "
                f"a short cohort would silently weaken G3's threshold"
            )
        return tuple(cohort)


@dataclass(frozen=True)
class TrainOnlyEvidence:
    """The proposer's view of the corpus: train scenarios and nothing else.

    A view rather than a convention — the proposer is handed this instead of
    the `Corpus`, so citing validation or holdout is not something it can do
    incorrectly, only something it can fail to do at all.
    """

    scenario_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_corpus(cls, corpus: Corpus) -> TrainOnlyEvidence:
        return cls(scenario_ids=frozenset(s.id for s in corpus.split(Split.TRAIN)))

    def cite(self, scenario_id: str, detail: str = "") -> Citation:
        if scenario_id not in self.scenario_ids:
            raise ProposalError(
                f"{scenario_id!r} is not a train-split scenario; the proposer may only cite "
                f"evidence it is permitted to see"
            )
        return Citation(source=scenario_id, split=Split.TRAIN, detail=detail)


@dataclass(frozen=True)
class MemoryEvidence:
    """Failure memory the proposer is permitted to learn from.

    This is the wire that was missing. `make_reflect_node` has written
    `MemoryRecord(kind="failure"|"success")` since M0 and nothing read them,
    so the system recorded lessons and never used one — self-modifying, but
    not self-learning (ADR 0065).

    **Records produced by a validation or holdout run are excluded**, because
    a reflect node running over such a scenario writes a record whose
    `run_id` is that scenario's id; citing it would leak the very set the
    proposer must not see. The exclusion is by known id rather than by
    allowlist: a production run has an arbitrary `run_id` that appears in no
    split, and production experience is exactly what this exists to learn
    from. So the rule is *deny what is known to be off-limits*, and the
    reason it is safe is that the leak we care about has an exact signature.
    """

    records: tuple[MemoryRecord, ...] = ()
    excluded: tuple[str, ...] = ()

    @classmethod
    def from_store(
        cls,
        store: MemoryStore,
        corpus: Corpus | None = None,
        *,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> MemoryEvidence:
        off_limits = _off_limits_run_ids(corpus)
        found = store.query("failure", agent_id=agent_id, limit=limit)
        admissible = tuple(r for r in found if r.run_id not in off_limits)
        blocked = tuple(r.id for r in found if r.run_id in off_limits)
        return cls(records=admissible, excluded=blocked)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(r.id for r in self.records)

    def cite(self, record_id: str, detail: str = "") -> Citation:
        if record_id not in self.ids:
            raise ProposalError(
                f"memory record {record_id!r} is not admissible evidence — it was either "
                f"never recorded, or it came from a validation/holdout run and citing it "
                f"would leak the set the proposer must not see"
            )
        return Citation(source=record_id, detail=detail, kind=CitationKind.MEMORY)

    def citations(self) -> tuple[Citation, ...]:
        """Every admissible record, cited with the feedback that motivated it."""
        return tuple(
            Citation(
                source=r.id,
                detail=str(r.content.get("verbal_feedback", ""))[:160],
                kind=CitationKind.MEMORY,
            )
            for r in self.records
        )


def _off_limits_run_ids(corpus: Corpus | None) -> frozenset[str]:
    if corpus is None:
        return frozenset()
    return frozenset(s.id for s in corpus.scenarios if s.split in (Split.VALIDATION, Split.HOLDOUT))
