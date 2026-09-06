"""P2 step 1 — ten new summary scenarios, and ONE new owner rule, written
down before any of them was recorded.

## Why this file exists

Three ADRs have now measured the knowledge layer on a store holding **exactly
one** entry (0155, 0175, 0184/0193). ADR 0193's closing finding names the
blocker in one sentence: *this corpus cannot produce a second knowledge entry*,
so everything about ranking BETWEEN lessons — the boost's real risk — is
unmeasurable on it. `knowledge_boost` is off "on judgement rather than
measurement" for exactly that reason.

A second entry needs a second **signature**, and `consolidate.default_signature`
keys a check-derived failure on the joined `check:<path>:<op>` of the checks
that failed. Every one of the corpus's fifteen recorded failures is
`check:working_memory.summary:max_words` — a word cap, one family, one lesson.
So a second lesson needs an owner check of a **different op** to fail, twice,
in two distinct runs.

## The rule, stated before the runs

> **Rule A — an attributed claim stays attributed.** When the passage states a
> forward-looking or contested claim and attributes it to an interested party
> in so many words ("the operator says…", "the council says…"), the summary
> may not present that claim as established fact. It must carry an attribution
> marker.

One regex, **constant across every scenario it is applied to** — nothing is
tuned per passage:

    (?i)\\b(said|says|say|claim|alleg|report|assert|accus|according|disput|
           deni|insist|unconfirmed|unverified)

`maintain` was in the first draft of that alternation and was struck out
before any recording: "pedestrian access maintained" is not an attribution and
the corpus already contains that sentence. A marker word with a common
non-attributive sense makes the check pass for the wrong reason.

It is a `regex` check on `working_memory.summary`, so a run that fails it and
nothing else keys on `check:working_memory.summary:regex` — a signature this
corpus has never produced, because the term checks that already use that op
have never failed (39 of 39).

## Disclosure — the recorded corpus was read before the rule was written

ADR 0192's rule, and the honest half of the method: candidate rules were
screened offline against the 39 recordings that already exist, to learn whether
*any* second failure family is reachable at all before spending quota on one
that is not. Six candidates were screened; their measured failure rates over
the scenarios each applies to are in `docs/research/i12e/results/screen.json`:

| candidate | applies | fails |
|---|---|---|
| money written with the £ symbol | 6 | 2 (33%) |
| the month is carried | 18 | 4 (22%) |
| **attribution is carried (Rule A)** | **9** | **9 (100%)** |
| the year is carried | 12 | 2 (17%) |
| the percentage is carried | 2 | 0 |
| the weekday is carried | 5 | 0 |

Rule A was chosen **because it fails**, and a reader is entitled to hold that
against it. Two things are offered against that objection and neither is a
refutation:

1. The rule is not shaped to a subset. It applies wherever its precondition
   holds and fails **9 of 9** — this agent has never once carried an
   attribution through a summary. That is a property of the agent, not of a
   check written to catch two particular answers.
2. **It is not applied to any existing scenario.** The nine that motivated it
   keep the checks they were recorded under, so ADR 0193's baseline is
   untouched and its arms remain comparable. The rule is carried only by the
   ten scenarios below, whose checks were written — in this committed file —
   **before** their first live call. That is ADR 0171's "strongest available
   order", and it is the only order under which a 100% base rate can be called
   a prediction rather than a description.

What a reader should still dispute: the summaries the rule fails are not
*wrong*. "signage from the month's start" is what the trust said would happen.
The owner's position is that a summary which launders an interested party's
forecast into fact is a defective summary; an owner who disagrees would delete
this rule, and the second lesson with it.

## The passages

Fourteen, in the corpus's register, each with exactly one attributed
forward-looking claim. **Ten train, four validation** — the split is fixed here
and never moved (ADR 0048).

## The cap, calibrated twice, in the open

The cap is a constant **40** on all but `sum-40`. What varies is the length of
the passage, and that is the variable this rig had to learn.

- **Draft 1** set caps of 32–36 on 60–68-word passages, reasoning from the
  existing corpus that this agent stays under its cap on passages of that
  length. `sum-40-lyth-brook` was recorded at 34 and came back at **36 words**.
- **Draft 2** raised the cap to a constant 40 and kept the passages.
  `sum-41`…`sum-45` came back at **41, 44, 43, 45 and 43 words** — five of five
  over. So the word cap was not being missed by a hair; on a 62–68-word passage
  this agent writes ~0.65 of the source regardless of what the cap says, and a
  roomier cap does not help.
- **Draft 3** — the block below marked *the SHORT block* — keeps the cap at 40
  and shortens the passage to 48–52 words, which is the band where the existing
  corpus stayed under (`sum-37` 59→31, `sum-38` 55→34).

Why it matters that length not be the failure: `default_signature` joins the
keys of **every** check a run failed, so a run that misses Rule A *and* the cap
keys on `check:…:regex>check:…:max_words` — a third signature, not the clean
second one. The six long scenarios are kept: they are honest recordings, they
fail two rules, and what they produce is a third lesson. The four short train
scenarios exist so that a **regex-only** lesson can form as well.

`sum-40` keeps the 34 it was recorded under, and nothing recorded is
re-recorded. Re-running a scenario until its answer is convenient is the one
thing a corpus may never do.
"""

from __future__ import annotations

import re
from typing import Any

# Rule A. One string, used by every scenario below; nothing per-passage.
ATTRIBUTION_RULE = (
    r"(?i)\b(said|says|say|claim|alleg|report|assert|accus|according|disput|deni"
    r"|insist|unconfirmed|unverified)"
)

SUMMARY_PATH = "working_memory.summary"


class Scenario:
    """One scenario to record. Plain data; the checks are derived, not typed."""

    def __init__(
        self, *, id: str, split: str, cap: int, terms: list[str], text: str, notes: str
    ) -> None:
        self.id = id
        self.split = split
        self.cap = cap
        self.terms = terms
        self.text = " ".join(text.split())
        self.notes = notes

    @property
    def objective(self) -> str:
        return f"summarise {self.id} in at most {self.cap} words"

    @property
    def working_memory(self) -> dict[str, Any]:
        return {"text": self.text, "max_words": self.cap, "must_mention": list(self.terms)}

    @property
    def checks(self) -> list[dict[str, Any]]:
        """The owner's checks, in the owner's declared order.

        Term checks first (the corpus's existing shape: `regex` with an inline
        `(?i)` over `re.escape`, ADR 0159), then Rule A, then the word cap and
        the `min_words: 1` that keeps a bare cap from accepting an empty
        summary (ADR 0171). The term checks and Rule A share one check KEY —
        `check:working_memory.summary:regex` — which is the merge
        `check_memory.check_key` documents and intends: "this field keeps
        omitting a required term" is one behaviour.
        """
        out: list[dict[str, Any]] = [
            {"path": SUMMARY_PATH, "op": "regex", "value": f"(?i){re.escape(t)}"}
            for t in self.terms
        ]
        out.append({"path": SUMMARY_PATH, "op": "regex", "value": ATTRIBUTION_RULE})
        out.append({"path": SUMMARY_PATH, "op": "max_words", "value": self.cap})
        out.append({"path": SUMMARY_PATH, "op": "min_words", "value": 1})
        return out


_ATTRIBUTED = (
    "synthetic passage; recorded live via claude_code on claude-opus-5[1m] "
    "(ADR 0201). One attributed forward-looking claim, and the owner's Rule A: "
    "an attributed claim stays attributed"
)

SCENARIOS: list[Scenario] = [
    Scenario(
        id="sum-40-lyth-brook",
        split="train",
        cap=34,
        terms=["Lyth Brook"],
        text="""
        The footbridge over Lyth Brook has been closed since a survey in June found rot in
        two of its four main beams. The parish council has ordered replacement timbers,
        which are due in October, and says the crossing should reopen before the winter.
        Walkers are being sent round by the ford at Bank End, which adds about a mile to
        the route. The bridge carries no vehicles.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-41-tarn-moss-peat",
        split="train",
        cap=40,
        terms=["Tarn Moss"],
        text="""
        Restoration of the peat at Tarn Moss has entered its second winter, with 4,200
        metres of plastic piling now driven to hold water on the bare hags. The contractor
        says the water table has already risen by twelve centimetres across the northern
        half. Sphagnum plugs go in next spring. The site remains open to walkers, though
        the boardwalk from the eastern gate is closed until March.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-42-harber-street-market",
        split="train",
        cap=40,
        terms=["Harber Street"],
        text="""
        The Tuesday market on Harber Street will move to the civic square from January
        while the street's drainage is replaced. Thirty-one of the thirty-eight traders
        have taken a pitch in the square; the rest have asked for a refund of their annual
        fee. The council says the market will return to Harber Street in the autumn.
        Stallholders will pay no rent for the first four weeks.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-43-crake-fell-mast",
        split="train",
        cap=40,
        terms=["Crake Fell"],
        text="""
        An application to raise the telecommunications mast on Crake Fell from eighteen to
        twenty-six metres has been withdrawn a week before it was due to be decided. The
        operator says a revised scheme with a slimmer lattice will be submitted in the new
        year. Two hundred and forty objections had been lodged, most of them about the
        view from the Ridge Way. The existing mast stays.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-44-orrell-baths",
        split="train",
        cap=40,
        terms=["Orrell Baths"],
        text="""
        Orrell Baths will keep its Victorian tiling under the refurbishment agreed last
        week, after conservation officers objected to the first design. The pool will close
        from February to November. The trust running the building says the extra tiling
        work adds nine weeks and about ninety thousand pounds, which it hopes to raise from
        a public appeal. The gym and the cafe stay open throughout.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-45-nether-gill-reservoir",
        split="train",
        cap=40,
        terms=["Nether Gill"],
        text="""
        Drawdown at Nether Gill reservoir has exposed the walls of the drowned farmstead
        for the first time since 2018. The water company says the level will be held low
        until spillway repairs finish in November, and has asked visitors to keep off the
        exposed bed, which is soft. The reservoir path is unaffected. Anglers have been
        told the season will not be extended to compensate.
        """,
        notes=_ATTRIBUTED,
    ),
    # --- the SHORT block (see "the cap, calibrated twice" above) -------------
    # 48-52-word passages under the same cap of 40. Everything else is
    # identical: one attributed forward-looking claim, the same Rule A, the
    # same check shape.
    Scenario(
        id="sum-46-thwaite-lane-bridge",
        split="validation",
        cap=40,
        terms=["Thwaite Lane"],
        text="""
        A seven-and-a-half-tonne weight limit came into force on the Thwaite Lane bridge on
        Monday, after an inspection found cracking in the eastern abutment. The county
        council says a full assessment will take six weeks and the limit may then be
        lifted. Buses now run through Sowerby, adding eleven minutes.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-47-eller-beck-hatchery",
        split="validation",
        cap=40,
        terms=["Eller Beck"],
        text="""
        The trout hatchery on Eller Beck will not stock the river this year, after a
        screening test found a parasite in two holding tanks. The fishery board says the
        tanks have been emptied and disinfected and that stocking should resume next
        season. Angling clubs upstream are unaffected.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-48-marsden-gate-quarry",
        split="validation",
        cap=40,
        terms=["Marsden Gate"],
        text="""
        Blasting at Marsden Gate quarry has been suspended since a house on Fold Lane
        complained of cracked plaster in August. The operator says its own monitors
        recorded vibration well inside the permitted limit. Crushing and haulage continue,
        with lorry movements unchanged at sixty a day.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-49-birkrigg-allotments",
        split="validation",
        cap=40,
        terms=["Birkrigg"],
        text="""
        Twenty-two of the ninety plots at the Birkrigg allotments will become a community
        orchard, a decision taken by the association's committee in September. The council,
        which owns the land, says the change needs no planning permission. Eleven people on
        the waiting list have been offered the southern terrace instead.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-50-garrow-tunnel",
        split="train",
        cap=40,
        terms=["Garrow tunnel"],
        text="""
        Water ingress has closed the towpath through Garrow tunnel until further notice,
        after a section of brick lining came away in October. The navigation trust says a
        survey boat will go through in December and repairs should follow in the spring.
        Boats are unaffected.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-51-hallam-croft-school",
        split="train",
        cap=40,
        terms=["Hallam Croft"],
        text="""
        The infant classes at Hallam Croft school will move into the refurbished east wing
        at half term, freeing the 1950s block for demolition next year. The governors say
        the playing field will not be built on. Two hundred and ten pupils are on roll.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-52-riddings-bakery",
        split="train",
        cap=40,
        terms=["Riddings"],
        text="""
        The bakery at Riddings will close its shop counter in November and sell only to
        wholesale customers, ending sixty years of retail trade. The owners say the
        wood-fired oven will keep running six days a week. Four of the eleven staff have
        been offered other roles.
        """,
        notes=_ATTRIBUTED,
    ),
    Scenario(
        id="sum-53-culvert-lane-flood",
        split="train",
        cap=40,
        terms=["Culvert Lane"],
        text="""
        Eleven houses on Culvert Lane were flooded on 3 November when a screen on the
        culvert blocked with branches. The drainage board says the screen will be replaced
        with a self-clearing design before next winter. The road reopened on 5 November
        after silt was cleared.
        """,
        notes=_ATTRIBUTED,
    ),
]

BY_ID = {s.id: s for s in SCENARIOS}
