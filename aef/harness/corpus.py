"""The golden corpus — recorded runs, split three ways, that never shrinks.

Three properties this module exists to guarantee.

**Splits are decided at record time and are immutable.** `train` is the only
split a proposer may cite (`grounded_in`); `validation` is what gates score
against; `holdout` is the owner's, rotated, and never shown to the proposer.
If a scenario could move between splits, holdout leaks into train and G3's
"beats the control cohort on held-out data" becomes a measurement of
memorisation. So the split is stored *inside* the scenario, and loading
verifies it against the directory it was found in — a scenario moved on disk
fails loudly rather than quietly joining a different split.

**The corpus never shrinks.** A gate suite that can be made to pass by
deleting the scenario that fails is not a gate suite. `CorpusManifest`
records every id ever admitted; `check_never_shrinks` fails if one goes
missing. This is checked in CI, from the base ref, so a candidate cannot
retire its own counterexample.

**Re-execution is deterministic.** A scenario pins the clock values its
original run observed (`fixed_clock`). Without that, re-executing produces
different `Context.now` values and every trace comparison diverges for
reasons that have nothing to do with the candidate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from aef.harness.trace_codec import (
    TRACE_FORMAT_VERSION,
    TraceCodecError,
    decode_trace,
    dumps,
    encode_trace,
    loads,
)
from aef.kernel.executor import NodeExecutionRecord
from aef.state import AEFState

MANIFEST_FILENAME = "manifest.json"


class Split(StrEnum):
    TRAIN = "train"  # the only split a proposer may cite
    VALIDATION = "validation"  # what the gates score against
    HOLDOUT = "holdout"  # the owner's; never shown to the proposer


class CorpusError(RuntimeError):
    pass


class CorpusShrankError(CorpusError):
    """A scenario that was previously admitted is gone. Deliberately its own
    exception type: this is not a normal validation failure, it is the one
    failure mode that would let a candidate erase its own counterexample."""


@dataclass(frozen=True)
class Scenario:
    id: str
    split: Split
    graph_id: str
    graph_version: str
    initial_state: AEFState
    trace: tuple[NodeExecutionRecord, ...]
    recorded_at: datetime
    notes: str = ""

    @property
    def clock_values(self) -> tuple[datetime, ...]:
        """Every `Context.now` the original run observed, in order."""
        return tuple(record.context.now for record in self.trace)

    def to_payload(self) -> dict[str, Any]:
        return {
            "format_version": TRACE_FORMAT_VERSION,
            "id": self.id,
            "split": self.split.value,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "initial_state": self.initial_state.model_dump(mode="json"),
            "trace": encode_trace(self.trace),
            "recorded_at": self.recorded_at.isoformat(),
            "notes": self.notes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Scenario:
        try:
            return cls(
                id=payload["id"],
                split=Split(payload["split"]),
                graph_id=payload["graph_id"],
                graph_version=payload["graph_version"],
                initial_state=AEFState.model_validate(payload["initial_state"]),
                trace=decode_trace(payload["trace"]),
                recorded_at=datetime.fromisoformat(payload["recorded_at"]),
                notes=payload.get("notes", ""),
            )
        except (KeyError, ValueError) as exc:
            raise CorpusError(f"malformed scenario payload: {exc}") from exc


def fixed_clock(scenario: Scenario) -> Callable[[], datetime]:
    """A `Services.clock` replaying the scenario's recorded timestamps.

    Pinning the clock is what makes re-execution comparable at all. Running
    past the recorded sequence raises rather than inventing a value: a
    candidate that takes MORE steps than the incumbent is a real behavioural
    difference, and silently handing it a fresh `now` would hide it behind a
    timestamp mismatch instead of reporting it.
    """
    remaining = list(scenario.clock_values)
    consumed = 0

    def clock() -> datetime:
        nonlocal consumed
        if not remaining:
            raise CorpusError(
                f"scenario {scenario.id!r} pinned {consumed} clock value(s) but the run asked "
                f"for another — the candidate executed more steps than the recording, which "
                f"is a behavioural difference to report, not a timestamp to invent"
            )
        consumed += 1
        return remaining.pop(0)

    return clock


@dataclass(frozen=True)
class CorpusManifest:
    """Every scenario id ever admitted, with its split. The never-shrinks
    ledger; lives in Zone B and is read from the base ref."""

    ids: dict[str, Split] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"scenarios": {sid: split.value for sid, split in sorted(self.ids.items())}}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CorpusManifest:
        raw = payload.get("scenarios", {})
        if not isinstance(raw, dict):
            raise CorpusError("manifest 'scenarios' must be an object")
        return cls(ids={sid: Split(value) for sid, value in raw.items()})


@dataclass(frozen=True)
class Corpus:
    root: Path
    scenarios: tuple[Scenario, ...] = ()

    def split(self, split: Split) -> tuple[Scenario, ...]:
        return tuple(s for s in self.scenarios if s.split is split)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(s.id for s in self.scenarios)

    def manifest(self) -> CorpusManifest:
        return CorpusManifest(ids={s.id: s.split for s in self.scenarios})


def scenario_path(root: Path, scenario: Scenario) -> Path:
    return root / scenario.split.value / f"{scenario.id}.json"


def save_scenario(root: Path, scenario: Scenario) -> Path:
    path = scenario_path(root, scenario)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(scenario.to_payload()))
    return path


def load_scenario(path: Path) -> Scenario:
    try:
        scenario = Scenario.from_payload(loads(path.read_text()))
    except TraceCodecError as exc:
        raise CorpusError(f"{path}: {exc}") from exc

    # The directory is a claim; the file is the record. A scenario moved
    # from holdout/ into train/ would otherwise silently become citable by
    # the proposer, which is precisely the leak the split exists to prevent.
    claimed = path.parent.name
    if claimed != scenario.split.value:
        raise CorpusError(
            f"{path}: scenario {scenario.id!r} declares split {scenario.split.value!r} but sits "
            f"in {claimed!r}/. A scenario's split is fixed at record time — moving files "
            f"between splits leaks the holdout into the proposer's evidence base."
        )
    if path.stem != scenario.id:
        raise CorpusError(
            f"{path}: filename {path.stem!r} does not match scenario id {scenario.id!r}"
        )
    return scenario


def load_corpus(root: Path) -> Corpus:
    scenarios: list[Scenario] = []
    for split in Split:
        directory = root / split.value
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            scenarios.append(load_scenario(path))

    duplicates = _duplicated(s.id for s in scenarios)
    if duplicates:
        raise CorpusError(f"duplicate scenario id(s) across splits: {sorted(duplicates)}")
    return Corpus(root=root, scenarios=tuple(scenarios))


def _duplicated(ids: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in ids:
        (dupes if value in seen else seen).add(value)
    return dupes


def save_manifest(root: Path, manifest: CorpusManifest) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / MANIFEST_FILENAME
    path.write_text(dumps(manifest.to_payload()))
    return path


def load_manifest(root: Path) -> CorpusManifest:
    path = root / MANIFEST_FILENAME
    if not path.is_file():
        return CorpusManifest()
    return CorpusManifest.from_payload(loads(path.read_text()))


def check_never_shrinks(corpus: Corpus, baseline: CorpusManifest) -> None:
    """Raise unless `corpus` still contains every id `baseline` recorded.

    Growth is fine and expected; a scenario changing split is not, because
    that is deletion from one split dressed as an addition to another.
    """
    missing = sorted(set(baseline.ids) - corpus.ids)
    if missing:
        raise CorpusShrankError(
            f"corpus shrank: {len(missing)} previously-admitted scenario(s) are gone: "
            f"{missing}. A suite that can be made to pass by deleting the failing case is "
            f"not a suite."
        )
    current = corpus.manifest().ids
    moved = sorted(
        f"{sid}: {baseline.ids[sid].value} -> {current[sid].value}"
        for sid in baseline.ids
        if current[sid] is not baseline.ids[sid]
    )
    if moved:
        raise CorpusShrankError(f"scenario(s) changed split, which erases evidence: {moved}")
