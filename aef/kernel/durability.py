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

Beyond the checkpointed `AEFState` itself, a backend also tracks a small
per-run "cursor" — the id of the node that should run next, or `None` once
the run has reached `END`. Without this, "resuming" a run means calling
`GraphExecutor.run()` with the latest checkpointed state, which restarts at
`graph.entry_node` and silently re-executes every node that already ran
(duplicating any non-pure side effects) — a real gap found by testing
resume, not a hypothetical one; see docs/adr/0009. `GraphExecutor.resume()`
is what actually continues a crashed/paused run correctly, and it depends
on this cursor.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from aef.state import AEFState, load_state


class CorruptedCheckpointError(RuntimeError):
    """A checkpoint file exists but its contents aren't valid JSON — a
    truncated write (e.g. a crash mid-`write_text`), a zero-byte file, or a
    hand-corrupted file. Reproduced directly: a genuinely truncated
    checkpoint raises a bare `json.JSONDecodeError` with no indication of
    which run_id/checkpoint_seq/path it came from. See docs/adr/0026."""


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

    @abstractmethod
    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        """Record which node should run next for `run_id`, or `None` if the
        run has reached `END`. Called after every super-step, alongside
        `save_checkpoint`."""
        raise NotImplementedError

    @abstractmethod
    def load_cursor(self, run_id: str) -> str | None:
        """The node id to resume at, or `None` if the run already completed.
        Callers distinguish "never started" from "completed" via
        `load_latest`/`list_checkpoints` returning nothing at all — this
        method alone cannot tell those two cases apart."""
        raise NotImplementedError


class InMemoryDurabilityBackend(DurabilityBackend):
    """Round-trips every checkpoint through JSON (not just object references)
    so the migration path (`load_state`) is genuinely exercised on every
    read, exactly as a real out-of-process backend would."""

    def __init__(self) -> None:
        self._store: dict[str, dict[int, str]] = {}
        self._cursors: dict[str, str | None] = {}

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

    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        self._cursors[run_id] = next_node

    def load_cursor(self, run_id: str) -> str | None:
        return self._cursors.get(run_id)


class FileDurabilityBackend(DurabilityBackend):
    """One JSON file per (run_id, checkpoint_seq) under `root_dir`, plus a
    `cursor.json` sidecar per run. Survives process restart without any
    external service — the honest stand-in for a "Postgres checkpointer
    suffices" deployment (report Recommendation #1)."""

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
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CorruptedCheckpointError(
                f"checkpoint {path} (run_id={run_id!r}, checkpoint_seq={checkpoint_seq}) "
                f"is not valid JSON: {exc}"
            ) from exc
        return load_state(raw)

    def list_checkpoints(self, run_id: str) -> list[int]:
        run_dir = self._root / run_id
        if not run_dir.exists():
            return []
        # Only `<int>.json` files are checkpoints — `cursor.json` and any
        # other non-checkpoint `.json` file sharing this directory (a stray
        # backup, a future sidecar file) must not be mistaken for one.
        # Reproduced directly: a single non-numeric-stem `.json` file here
        # used to raise ValueError from `int(p.stem)` and take down
        # list_checkpoints — and therefore load_latest — for the entire
        # run_id, not just the offending file.
        return sorted(int(p.stem) for p in run_dir.glob("*.json") if p.stem.isdigit())

    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        cursor_path = self._run_dir(run_id) / "cursor.json"
        cursor_path.write_text(json.dumps({"next_node": next_node}))

    def load_cursor(self, run_id: str) -> str | None:
        cursor_path = self._root / run_id / "cursor.json"
        if not cursor_path.exists():
            return None
        data = json.loads(cursor_path.read_text())
        next_node = data.get("next_node")
        return next_node if isinstance(next_node, str) else None


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

    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        raise NotImplementedError

    def load_cursor(self, run_id: str) -> str | None:
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

    def save_cursor(self, run_id: str, next_node: str | None) -> None:
        raise NotImplementedError

    def load_cursor(self, run_id: str) -> str | None:
        raise NotImplementedError
