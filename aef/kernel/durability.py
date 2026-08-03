"""`DurabilityBackend` — checkpoint persistence (report §2.3 tier 1 / blueprint
Part 2.3). Every super-step's resulting `AEFState` is written through here.

Deviation from the blueprint's literal Part 2.3 (Temporal-wrapped, Postgres-
tiered durability): Phase 0/1 ships `InMemoryDurabilityBackend` and
`FileDurabilityBackend` only — both real and tested, both requiring zero new
infrastructure. The report's own Recommendation #1 says a durable backend
like Temporal is only needed once a run must "survive worker restarts or
exceed ~1 hour of wall-clock" — not true of anything built here yet. Postgres
and Temporal backends are declared as typed stubs so swapping them in later
is a pure adapter addition; see docs/adr/0002.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from aef.state import AEFState, load_state


class DurabilityBackend(ABC):
    @abstractmethod
    def save_checkpoint(self, state: AEFState) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_latest(self, run_id: str) -> AEFState | None:
        raise NotImplementedError

    @abstractmethod
    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        raise NotImplementedError

    @abstractmethod
    def list_checkpoints(self, run_id: str) -> list[int]:
        raise NotImplementedError


class InMemoryDurabilityBackend(DurabilityBackend):
    """Round-trips every checkpoint through JSON (not just object references)
    so the migration path (`load_state`) is genuinely exercised on every
    read, exactly as a real out-of-process backend would."""

    def __init__(self) -> None:
        self._store: dict[str, dict[int, str]] = {}

    def save_checkpoint(self, state: AEFState) -> None:
        run = self._store.setdefault(state.run_id, {})
        run[state.checkpoint_seq] = state.model_dump_json()

    def load_latest(self, run_id: str) -> AEFState | None:
        run = self._store.get(run_id)
        if not run:
            return None
        latest_seq = max(run)
        return load_state(json.loads(run[latest_seq]))

    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        run = self._store.get(run_id)
        if not run or checkpoint_seq not in run:
            return None
        return load_state(json.loads(run[checkpoint_seq]))

    def list_checkpoints(self, run_id: str) -> list[int]:
        return sorted(self._store.get(run_id, {}))


class FileDurabilityBackend(DurabilityBackend):
    """One JSON file per (run_id, checkpoint_seq) under `root_dir`. Survives
    process restart without any external service — the honest stand-in for
    a "Postgres checkpointer suffices" deployment (report Recommendation #1)."""

    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self._root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def save_checkpoint(self, state: AEFState) -> None:
        path = self._run_dir(state.run_id) / f"{state.checkpoint_seq}.json"
        path.write_text(state.model_dump_json())

    def load_latest(self, run_id: str) -> AEFState | None:
        checkpoints = self.list_checkpoints(run_id)
        if not checkpoints:
            return None
        return self.load_checkpoint(run_id, max(checkpoints))

    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        path = self._root / run_id / f"{checkpoint_seq}.json"
        if not path.exists():
            return None
        return load_state(json.loads(path.read_text()))

    def list_checkpoints(self, run_id: str) -> list[int]:
        run_dir = self._root / run_id
        if not run_dir.exists():
            return []
        return sorted(int(p.stem) for p in run_dir.glob("*.json"))


class PostgresDurabilityBackend(DurabilityBackend):
    """Phase 2 stub. Would back onto the same PostgreSQL instance already
    used for checkpoints in production LangGraph deployments (report §2.3
    tier 1). No `psycopg`/`psycopg2` import here — nothing is implemented
    yet, so nothing vendor-specific needs importing."""

    def __init__(self, dsn: str) -> None:
        raise NotImplementedError(
            "PostgresDurabilityBackend is a Phase 2 stub; see docs/roadmap.md"
        )

    def save_checkpoint(self, state: AEFState) -> None:
        raise NotImplementedError

    def load_latest(self, run_id: str) -> AEFState | None:
        raise NotImplementedError

    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        raise NotImplementedError

    def list_checkpoints(self, run_id: str) -> list[int]:
        raise NotImplementedError


class TemporalDurabilityBackend(DurabilityBackend):
    """Phase 2+ stub for the "tier 2" durability guarantee (blueprint §2.3):
    wraps node execution as Temporal Activities so a dead worker's run can be
    resumed by replaying Workflow event history on another worker. Gated
    behind the report's own change trigger — only worth adding once a run
    must survive worker restarts or exceed ~1hr wall-clock (Recommendation #1).
    """

    def __init__(self, *, task_queue: str) -> None:
        raise NotImplementedError(
            "TemporalDurabilityBackend is a Phase 2+ stub; see docs/roadmap.md"
        )

    def save_checkpoint(self, state: AEFState) -> None:
        raise NotImplementedError

    def load_latest(self, run_id: str) -> AEFState | None:
        raise NotImplementedError

    def load_checkpoint(self, run_id: str, checkpoint_seq: int) -> AEFState | None:
        raise NotImplementedError

    def list_checkpoints(self, run_id: str) -> list[int]:
        raise NotImplementedError
