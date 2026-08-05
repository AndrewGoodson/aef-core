"""What a status surface is allowed to claim.

This module is deliberately the first thing built, and it contains no
rendering. A dashboard is a trust surface: a wrong number on it is believed by
someone who has stopped reading the underlying data, which is the whole reason
they wanted a dashboard. So the constraints go in a type before they go in a
template.

Three decisions live here, each with an ADR (0107) behind it:

1. **A panel with no data cannot render green.** Not by convention — `Unknown`
   has no `state` field at all, so there is no branch in which it produces
   `HEALTHY`. `Digest` already carries `halt_channel_configured` and
   `runs_recorded` for exactly this reason, stated in its own source: "a system
   that reports nothing looks identical to one with nothing to report." A
   dashboard is where that stops being a nuisance and becomes authoritative.

2. **The page is read-only.** `FORBIDDEN_HTML_CONSTRUCTS` is declared here and
   imported by the renderer's test rather than re-listed there — the same
   derived-not-duplicated rule the gate catalogue follows, because two lists
   nobody compares drift (ADR 0091).

3. **No field is emitted whose disclosure was not decided.** `disclosure_of`
   raises on an unregistered field. An export is a file that gets committed,
   attached to tickets and pasted into chat; "nothing sensitive here" is a
   claim, and this makes it one somebody had to type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class PanelState(StrEnum):
    """What a panel says about the thing it watches.

    `UNKNOWN` is not a styling choice and not a third kind of bad. It is the
    honest reading when the data that would answer the question is absent —
    and it is the reading this whole module exists to make unavoidable.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class UnknownReason(StrEnum):
    """Why a panel cannot answer.

    Enumerated rather than free-text because the operator's next action
    differs per reason, and "unknown" with no cause sends them looking in the
    wrong place — the defect class ADR 0074 named ("a refusal that misnames
    its own cause sends the operator to fix the wrong thing").
    """

    NO_LEDGER = "no_ledger"
    LEDGER_EMPTY = "ledger_empty"
    LEDGER_UNVERIFIED = "ledger_unverified"
    NO_RUNS_RECORDED = "no_runs_recorded"
    MONITOR_NEVER_RAN = "monitor_never_ran"
    WINDOW_TOO_YOUNG = "window_too_young"
    HALT_CHANNEL_UNCONFIGURED = "halt_channel_unconfigured"
    CORPUS_EMPTY = "corpus_empty"
    NO_GRAPH = "no_graph"
    NO_LOOP_STATE = "no_loop_state"
    EXPORT_MISSING = "export_missing"
    EXPORT_STALE = "export_stale"
    EXPORT_UNREADABLE = "export_unreadable"


@dataclass(frozen=True)
class Unknown:
    """No data behind this panel.

    Has no `state` field, on purpose. The rule "a panel with no data must not
    render green" is not enforced by a check that could be forgotten; there is
    simply no attribute to read, and `mypy --strict` rejects any access to
    `.state` on a `Reading` that has not been narrowed to `Known` first.
    """

    reason: UnknownReason
    remedy: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reason, UnknownReason):
            raise TypeError(
                f"reason must be an UnknownReason, got {type(self.reason).__name__}. "
                f"A free-text cause is one nobody can route on."
            )


@dataclass(frozen=True)
class Known(Generic[T]):
    """A value, and what it means.

    Refuses `PanelState.UNKNOWN`: holding a value and reporting that you have
    none is a contradiction, and permitting it would reopen by the back door
    exactly the confusion `Unknown` exists to close.
    """

    value: T
    state: PanelState

    def __post_init__(self) -> None:
        # Found by this milestone's adversarial round, and it defeated the
        # module's central claim in four lines using nothing but the real API:
        #
        #     Digest(...).acceptance_rate  ->  None   (when proposed == 0)
        #     Known(value=None, state=HEALTHY)  ->  a GREEN panel
        #
        # `Digest.acceptance_rate`, `beating_manual_editing` and
        # `MonitorResult.observed_pass_rate` all return `X | None` where None
        # means "nothing to compare" — which is precisely UNKNOWN wearing an
        # Optional. An adapter converting those to panels would have produced
        # a green dashboard for a loop that had never run.
        #
        # So None is refused here rather than handled downstream: the None
        # branch of an optional IS the Unknown branch, and making the caller
        # write that out is the only version of this rule that survives the
        # next adapter somebody adds.
        if self.value is None:
            raise ValueError(
                "Known(value=None) is the Unknown case wearing an Optional. Every source "
                "in this repo that can answer 'nothing to compare' says so with None — "
                "Digest.acceptance_rate, Digest.beating_manual_editing, "
                "MonitorResult.observed_pass_rate. Map that branch to "
                "Unknown(reason=...) explicitly; the operator needs the cause, and a "
                "green panel over a None is the exact failure this module exists to stop."
            )
        # `PanelState` is a StrEnum, so its members ARE strings — which means
        # `Known(value=1, state="unknown")` slipped past the identity check
        # below and produced a Known that claimed to be Unknown. Reproduced.
        if not isinstance(self.state, PanelState):
            raise TypeError(
                f"state must be a PanelState, got {type(self.state).__name__}. PanelState is "
                f"a StrEnum, so a bare string compares unequal to every member under `is` "
                f"and silently defeats both this guard and Panel.is_green."
            )
        if self.state is PanelState.UNKNOWN:
            raise ValueError(
                "Known(state=UNKNOWN) is a contradiction — a reading that holds a value "
                "knows something. Return Unknown(reason=...) instead, which carries the "
                "cause the operator needs."
            )

    @classmethod
    def optional(
        cls,
        value: T | None,
        state: PanelState,
        *,
        reason: UnknownReason,
        remedy: str = "",
    ) -> Reading[T]:
        """The honest conversion for a source that returns `X | None`.

        Provided because refusing None without offering the correct spelling
        just relocates the mistake — the next adapter would write
        `Known(value=x or 0, ...)`, which is the same green panel with an
        extra step.
        """
        if value is None:
            return Unknown(reason=reason, remedy=remedy)
        return cls(value=value, state=state)


# Generic alias. `Reading[int]` is either "we don't know" or "we know, and here
# is what it means" — with no third case, and no way to spell "we don't know,
# and it's fine."
Reading = Unknown | Known[T]


@dataclass(frozen=True)
class PanelSpec:
    """One panel's contract: what it watches, and precisely what makes it
    UNKNOWN rather than HEALTHY.

    Written down per panel because "it shows unknown when there's no data" is
    the kind of sentence that sounds complete and specifies nothing.
    """

    key: str
    title: str
    watches: str
    unknown_when: tuple[UnknownReason, ...]

    def __post_init__(self) -> None:
        if not self.unknown_when:
            raise ValueError(
                f"panel {self.key!r} declares no UNKNOWN condition. Every panel in this "
                f"system reads from data that can be absent; a panel that claims it "
                f"cannot be unknown has not been thought about."
            )


@dataclass(frozen=True)
class Panel:
    """A spec bound to a reading.

    `state` is the single place a `Reading` becomes a `PanelState`, and it is
    total: `Unknown` maps to `UNKNOWN` and nothing else can.
    """

    spec: PanelSpec
    reading: Reading[object]

    def __post_init__(self) -> None:
        # Reproduced in this milestone's adversarial round: any object with a
        # `.state` attribute set to HEALTHY rendered green, because
        # `isinstance(reading, Unknown)` was False and the else-branch trusted
        # whatever it was handed. Duck typing is the wrong default at a trust
        # boundary — `Reading` is a closed union of exactly two cases and this
        # keeps it closed at runtime as well as in the type.
        if not isinstance(self.reading, (Unknown, Known)):
            raise TypeError(
                f"reading must be Unknown or Known, got {type(self.reading).__name__}. "
                f"Reading is a closed union of two cases; anything else reaching here "
                f"renders whatever `.state` it happens to carry."
            )

    @property
    def state(self) -> PanelState:
        if isinstance(self.reading, Unknown):
            return PanelState.UNKNOWN
        return self.reading.state

    @property
    def is_green(self) -> bool:
        return self.state is PanelState.HEALTHY


# --------------------------------------------------------------------------
# The panel catalogue (Milestone 1a).
# --------------------------------------------------------------------------

PANELS: tuple[PanelSpec, ...] = (
    PanelSpec(
        key="halt",
        title="Kill switch",
        watches="whether the loop is halted, and why",
        unknown_when=(UnknownReason.NO_LOOP_STATE,),
    ),
    PanelSpec(
        key="ledger_integrity",
        title="Ledger integrity",
        watches="the hash chain over every loop event",
        unknown_when=(UnknownReason.NO_LEDGER, UnknownReason.NO_LOOP_STATE),
    ),
    PanelSpec(
        key="halt_channel",
        title="Halt notification",
        watches="whether a halt would reach a human",
        unknown_when=(UnknownReason.HALT_CHANNEL_UNCONFIGURED, UnknownReason.NO_LOOP_STATE),
    ),
    PanelSpec(
        key="acceptance",
        title="Acceptance rate",
        watches="merged over proposed, in the window",
        unknown_when=(
            UnknownReason.NO_LEDGER,
            UnknownReason.LEDGER_EMPTY,
            UnknownReason.WINDOW_TOO_YOUNG,
        ),
    ),
    PanelSpec(
        key="post_merge",
        title="Post-merge health",
        watches="live outcomes after each merge, and rollbacks",
        unknown_when=(
            UnknownReason.MONITOR_NEVER_RAN,
            UnknownReason.NO_RUNS_RECORDED,
            UnknownReason.WINDOW_TOO_YOUNG,
        ),
    ),
    PanelSpec(
        key="drift",
        title="Cumulative drift",
        watches="how far Zone A has moved from the blessed baseline",
        unknown_when=(UnknownReason.NO_LOOP_STATE, UnknownReason.LEDGER_EMPTY),
    ),
    PanelSpec(
        key="corpus",
        title="Golden corpus",
        watches="scenario count, and that it never shrinks",
        unknown_when=(UnknownReason.CORPUS_EMPTY, UnknownReason.NO_LOOP_STATE),
    ),
    PanelSpec(
        key="agent_graph",
        title="Agent graph",
        watches="node topology, side effects, HITL-gated edges",
        unknown_when=(UnknownReason.NO_GRAPH,),
    ),
    PanelSpec(
        key="loop_graph",
        title="Proposal lifecycle",
        watches="occupancy of each state from proposed to merged",
        unknown_when=(UnknownReason.NO_LEDGER, UnknownReason.LEDGER_EMPTY),
    ),
    PanelSpec(
        key="runs",
        title="Recorded runs",
        watches="whether any agent traffic was captured at all",
        unknown_when=(UnknownReason.NO_RUNS_RECORDED,),
    ),
)

PANELS_BY_KEY: dict[str, PanelSpec] = {spec.key: spec for spec in PANELS}


def panel_spec(key: str) -> PanelSpec:
    try:
        return PANELS_BY_KEY[key]
    except KeyError:
        raise KeyError(f"no panel {key!r}; known panels are {sorted(PANELS_BY_KEY)}") from None


# --------------------------------------------------------------------------
# Read-only (Milestone 1c).
# --------------------------------------------------------------------------

# Declared here, asserted by the renderer's tests. A dashboard with controls is
# an unaudited control plane reachable by anyone who can open a file — no
# authentication, no audit log entry, no HITL gate. The loop's whole approval
# story routes through a signed manifest held by a person; a button on a web
# page is a second door into it that nothing in this repo would record.
FORBIDDEN_HTML_CONSTRUCTS: tuple[str, ...] = (
    "<form",
    "<button",
    "<input",
    "<textarea",
    "onclick=",
    "onsubmit=",
    "onchange=",
    "fetch(",
    "XMLHttpRequest",
    "navigator.sendBeacon",
    "WebSocket",
    "localStorage.setItem",
    "document.cookie",
)


# --------------------------------------------------------------------------
# Disclosure (Milestone 1d).
# --------------------------------------------------------------------------


class Disclosure(StrEnum):
    PUBLIC = "public"
    """Safe in a file that gets committed and pasted into a ticket."""

    REDACTED = "redacted"
    """Emitted as a count, a digest or a type name — never the value."""

    EXCLUDED = "excluded"
    """Never emitted in any form."""


class DisclosureError(RuntimeError):
    """A field was emitted whose disclosure nobody decided."""


# Every field the export may carry, with the decision and its reason. An
# unregistered field raises rather than defaulting — a default here would be a
# policy applied to fields nobody looked at, which is the opposite of the point.
FIELD_DISCLOSURE: dict[str, Disclosure] = {
    # Identity and provenance of the export itself.
    "schema_version": Disclosure.PUBLIC,
    "generated_at": Disclosure.PUBLIC,
    "repo_name": Disclosure.PUBLIC,
    "graph_id": Disclosure.PUBLIC,
    "graph_version": Disclosure.PUBLIC,
    # Absolute paths leak the operator's home directory and the machine's
    # layout, and break the byte-stability the export is meant to have.
    "repo_root": Disclosure.EXCLUDED,
    "state_dir": Disclosure.EXCLUDED,
    "absolute_path": Disclosure.EXCLUDED,
    # Ledger. The head hash is a digest of data that is itself in the repo.
    "ledger_verified": Disclosure.PUBLIC,
    "ledger_entry_count": Disclosure.PUBLIC,
    "ledger_head_hash": Disclosure.PUBLIC,
    "ledger_error": Disclosure.PUBLIC,
    # Digest counters — aggregates, no payload.
    "proposed": Disclosure.PUBLIC,
    "merged": Disclosure.PUBLIC,
    "rejected": Disclosure.PUBLIC,
    "escalated": Disclosure.PUBLIC,
    "rolled_back": Disclosure.PUBLIC,
    "blessed": Disclosure.PUBLIC,
    "halts": Disclosure.PUBLIC,
    "security_events": Disclosure.PUBLIC,
    "scenarios_added": Disclosure.PUBLIC,
    "drift": Disclosure.PUBLIC,
    "owner_edits": Disclosure.PUBLIC,
    "runs_recorded": Disclosure.PUBLIC,
    "halt_channel_configured": Disclosure.PUBLIC,
    # Halt state. The reason is the operator's own words and is the entire
    # point of showing the halt; it is public deliberately, and the operator
    # writing it is the one deciding what it says.
    "kill_switch_engaged": Disclosure.PUBLIC,
    "kill_switch_reason": Disclosure.PUBLIC,
    # Candidate identity. All of this is already in git history.
    "proposal_id": Disclosure.PUBLIC,
    "branch": Disclosure.PUBLIC,
    "base_sha": Disclosure.PUBLIC,
    "head_sha": Disclosure.PUBLIC,
    "commit_message": Disclosure.PUBLIC,
    "gate_outcomes": Disclosure.PUBLIC,
    "approved_by": Disclosure.PUBLIC,
    # Graph topology.
    "node_id": Disclosure.PUBLIC,
    "edge_targets": Disclosure.PUBLIC,
    "side_effects": Disclosure.PUBLIC,
    "deterministic": Disclosure.PUBLIC,
    "requires_hitl": Disclosure.PUBLIC,
    "relative_path": Disclosure.PUBLIC,
    # Run telemetry.
    "run_id": Disclosure.PUBLIC,
    "node_duration_ms": Disclosure.PUBLIC,
    "token_count": Disclosure.PUBLIC,
    "model_name": Disclosure.PUBLIC,
    "pass_rate": Disclosure.PUBLIC,
    # Error text is the field most likely to carry a secret by accident: a
    # traceback that stringifies a connection URL, a client that echoes an
    # Authorization header. The type and the count answer the operator's
    # question ("is it failing, and how"); the message does not, and cannot be
    # scanned safely.
    "error_message": Disclosure.REDACTED,
    "error_type": Disclosure.PUBLIC,
    "error_count": Disclosure.PUBLIC,
    # A tenant tag list in a shared file is a customer list. The canary needs
    # per-tenant stratification; the dashboard needs only the shape of it.
    "tenant_tag": Disclosure.REDACTED,
    "tenant_count": Disclosure.PUBLIC,
    # The salt fingerprint is a deterministic function of the salt. ADR 0106
    # made it a 200k-iteration PBKDF2 precisely because it is an offline
    # oracle; publishing it in a file that gets pasted around hands an attacker
    # the oracle and the leisure to use it. Restarts prove same-population
    # against a fingerprint held in the loop state, not one in the export.
    "canary_salt_fingerprint": Disclosure.EXCLUDED,
    "canary_keyed": Disclosure.PUBLIC,
    "canary_percent": Disclosure.PUBLIC,
    # Never, in any form.
    "prompt_text": Disclosure.EXCLUDED,
    "response_text": Disclosure.EXCLUDED,
    "tool_arguments": Disclosure.EXCLUDED,
    "working_memory": Disclosure.EXCLUDED,
    "retrieved_context": Disclosure.EXCLUDED,
    "signing_key": Disclosure.EXCLUDED,
    "canary_salt": Disclosure.EXCLUDED,
    "api_key": Disclosure.EXCLUDED,
    "environment": Disclosure.EXCLUDED,
}


def disclosure_of(field: str) -> Disclosure:
    """The decided disclosure for `field`, or raise.

    Raising is the enforcement of the program's HARD-STOP #7. A default would
    silently apply somebody's guess to every field added later, which is how a
    decision becomes an accident.
    """
    try:
        return FIELD_DISCLOSURE[field]
    except KeyError:
        raise DisclosureError(
            f"field {field!r} has no disclosure decision. Add it to FIELD_DISCLOSURE with "
            f"a reason before emitting it — an export is committed, attached to tickets and "
            f"pasted into chat, and 'nothing sensitive here' is a claim, not an argument."
        ) from None


def emittable(field: str) -> bool:
    """Whether `field` may appear in the export at all, in any form."""
    return disclosure_of(field) is not Disclosure.EXCLUDED
