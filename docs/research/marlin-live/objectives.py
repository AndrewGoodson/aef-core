"""The ten objectives, drawn from marlin's own files (ADR 0204, step 2).

Every one is a question `marlin-source` exists to answer, and every fact in
every one is read out of the repository rather than invented:

- `pipeline/jurisdictions/{cape-coral,lee,hillsborough,pinellas,manatee,
  sarasota,fl-state}.yaml` and `_county.template.yaml` — the connector, the
  `sync_mode`, the `cursor_field`, the `page_size`, the `grace_days`, the
  `enabled` flag and the comments beside each;
- `AGENTS.md` — "Keep scheduled ingestion disabled until two manual runs
  reconcile source, fetched, lake, and published counts and live readback
  passes" and "Event dates are data, never ingestion watermarks";
- `docs/COUNTY_ONBOARDING.md` and `.claude/skills/county-onboard/SKILL.md` —
  the seven-step procedure this agent carries out;
- the commit history — `bdc3ab9` (Cape Coral permits via public ArcGIS),
  `35d6e2c` (key permits on row-unique objectid, not Permit_Number),
  `a0b3e5e` (lowercase objectid cursor field), `598d5ed` (Hillsborough +
  Pinellas), `3e65228` (ArcGIS count retry).

**No objective states a date.** ADR 0200's F-P1-3 measured a corpus whose
owner checks pinned absolute day counts flipping from pass to fail on one day
of calendar drift, because the gates compare a LIVE candidate against a
cassette-replayed incumbent and the model answers from its own clock. Nothing
here decays.

The `facts` on each objective are what the screen (step 3) uses to decide
whether a candidate rule APPLIES to that objective. They are properties of the
question, written here before any answer existed.
"""

from __future__ import annotations

from typing import TypedDict

# The one sentence that separates arm A from arm B (ADR 0204 §F-Q1-1).
#
# marlin's personas are written for a tool-using coding agent — "Reproduce
# locally first", "inspect the repository, diffs, test output". `aef migrate`
# turns each into the SYSTEM message of one tool-less single-turn completion,
# and every objective here names repository files. Arm A (no preamble)
# measured what that produces. This sentence is the whole of arm B, and it is
# the adaptation an adopter of a prompt-file repo has to make by hand.
NO_TOOLS_PREAMBLE = (
    "You are answering as a single completion with no repository access, no "
    "shell and no tools. Every fact you need is stated in this message. Do "
    "not propose to inspect files and do not describe inspecting them: rule "
    "on the stated facts alone, and say what evidence is missing if any is.\n\n"
)


class Objective(TypedDict):
    id: str
    facts: dict[str, object]
    text: str


OBJECTIVES: tuple[Objective, ...] = (
    {
        "id": "src-01-cape-coral-cursor",
        "facts": {
            "arcgis": True,
            "count_mismatch": False,
            "source_count": 57912,
            "fetched_count": 57912,
            "proposes_event_date_cursor": True,
            "authoritative_count_available": True,
        },
        "text": (
            "pipeline/jurisdictions/cape-coral.yaml declares the `permits` dataset as "
            "connector: arcgis, sync_mode: snapshot, id_field: objectid, "
            "cursor_field: objectid, cursor_type: objectid, page_size: 2000, against "
            "the City of Cape Coral public Building Permits MapServer layer. The "
            "layer also carries a `lastchangedon` field. A manual run queried the "
            "layer with returnCountOnly=true and got 57912; it fetched 57912 rows, "
            "wrote 57912 to the lake and published 57912. A change is proposed: move "
            "the dataset to sync_mode: incremental with cursor_field: issuedate and "
            "grace_days: 3. Is that manual run reconciled, and may the proposed "
            "cursor change be made?"
        ),
    },
    {
        "id": "src-02-lee-wells-late-arrival",
        "facts": {
            "arcgis": True,
            "count_mismatch": False,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
            "grace_days_in_question": True,
            "no_run_evidence": True,
        },
        "text": (
            "pipeline/jurisdictions/lee.yaml declares the `wells` dataset as "
            "connector: arcgis, sync_mode: incremental, id_field: GlobalID, "
            "cursor_field: last_edited_date, cursor_type: datetime, grace_days: 7, "
            "against the Lee County WellsPermittedLeeCounty FeatureServer. Its "
            "comment says ISSUE_DATE remains the business/event date only. A record "
            "whose ISSUE_DATE is five months older than the previous run's watermark "
            "was edited at the source after that watermark. State whether the next "
            "incremental run fetches that record, what happens to it if the same run "
            "is replayed, and what evidence a manual run must produce before this "
            "dataset's schedule may be enabled."
        ),
    },
    {
        "id": "src-03-hillsborough-full-page-at-cap",
        "facts": {
            "arcgis": True,
            "count_mismatch": False,
            "full_page_at_cap": True,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": False,
        },
        "text": (
            "A Hillsborough `parcels` pull (pipeline/jurisdictions/hillsborough.yaml, "
            "connector: swfwmd_parcels, id_field: OBJECTID, page_size: 1000, against "
            "the SWFWMD parcel_search MapServer layer 7) returned exactly 1000 "
            "features in one page. The response body carried no exceededTransferLimit "
            "key at all, and requesting the next page returned zero features. The run "
            "reports fetched 1000, lake 1000, published 1000, and no separate count "
            "query was issued. Is this run reconciled, and may the dataset's schedule "
            "be enabled on this evidence?"
        ),
    },
    {
        "id": "src-04-pinellas-count-mismatch",
        "facts": {
            "arcgis": True,
            "count_mismatch": True,
            "source_count": 41377,
            "fetched_count": 41290,
            "left_behind": 87,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
        },
        "text": (
            "A Pinellas `parcels` run (pipeline/jurisdictions/pinellas.yaml, "
            "connector: swfwmd_parcels, page_size: 1000) issued the authoritative "
            "returnCountOnly=true query "
            "and got 41377. The run then fetched 41290 rows, wrote 41290 to the lake "
            "and published 41290. Parquet readback returned 41290 and every record id "
            "was unique. Classify this run and state exactly what the report must "
            "carry."
        ),
    },
    {
        "id": "src-05-sunbiz-no-count-endpoint",
        "facts": {
            "arcgis": False,
            "count_mismatch": False,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": False,
        },
        "text": (
            "The fl-state `entities` dataset (pipeline/jurisdictions/fl-state.yaml, "
            "connector: sunbiz, sync_mode: incremental, grace_days: 7, "
            "enabled: false) reads daily fixed-width delta files over public SFTP. "
            "There is no count endpoint and no documented source-equivalent count "
            "query: the delta directory is a list of files. Two manual runs each "
            "fetched 12004 records; both reconciled fetched against lake against "
            "published at 12004, Parquet readback returned 12004 both times, and "
            "record ids were unique in both. May this dataset be enabled?"
        ),
    },
    {
        "id": "src-06-lee-accela-credentials",
        "facts": {
            "arcgis": False,
            "count_mismatch": False,
            "proposes_event_date_cursor": True,
            "authoritative_count_available": False,
            "accela": True,
        },
        "text": (
            "pipeline/jurisdictions/lee.yaml declares the `permits` dataset as "
            "connector: accela, agency: LEECO, env: PROD, module: Building, "
            "publication_cursor_field: null, enabled: false, with the comment "
            "'Do not enable until credentials AND a verified publication filter are "
            "configured. openedDate is an event date and is unsafe as cursor.' "
            "Marlin Key Vault now holds accela-app-id, accela-app-secret, "
            "accela-username and accela-password. The proposal is to set "
            "enabled: true and use openedDate as the publication cursor with "
            "grace_days: 14. Rule on it."
        ),
    },
    {
        "id": "src-07-cape-coral-record-id",
        "facts": {
            "arcgis": True,
            "count_mismatch": True,
            "source_count": 57912,
            "fetched_count": 57912,
            "left_behind": 0,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
            "duplicate_ids": True,
        },
        "text": (
            "Commit 35d6e2c in this repository is 'fix(cape-coral): key permits on "
            "row-unique objectid, not Permit_Number', because the City layer emits "
            "one row per contractor sub-record and Permit_Number repeats. A change is "
            "now proposed that sets id_field back to Permit_Number and deduplicates "
            "on it. The layer's returnCountOnly=true query returns 57912; the "
            "proposed run fetches 57912 rows and publishes 41638 after "
            "deduplication. State the effect on the source/fetched/lake/published "
            "reconciliation and rule on the change."
        ),
    },
    {
        "id": "src-08-manatee-duplicates-suppressed",
        "facts": {
            "arcgis": True,
            "count_mismatch": True,
            "source_count": 30112,
            "fetched_count": 30112,
            "left_behind": 0,
            "published_count": 30110,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
            "duplicate_ids": True,
        },
        "text": (
            "A second manual run of the Manatee `permits` dataset "
            "(pipeline/jurisdictions/manatee.yaml, connector: manatee_permits, "
            "id_field: OBJECTID, page_size: 2000) reports "
            "authoritative source count 30112, fetched 30112, lake 30112 and "
            "published 30110, with two record ids suppressed as duplicates by the "
            "publisher. Live readback of the status API returned 30110. The first "
            "manual run reported the same four numbers. Is this pair of runs "
            "reconciled, and may the schedule be enabled?"
        ),
    },
    {
        "id": "src-09-template-zero-grace",
        "facts": {
            "arcgis": True,
            "count_mismatch": False,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
            "grace_days_in_question": True,
            "zero_grace": True,
        },
        "text": (
            "A new county file copied from pipeline/jurisdictions/"
            "_county.template.yaml proposes a public-permits dataset with "
            "connector: arcgis, cursor_field: EditDate, cursor_type: epoch_ms, "
            "grace_days: 0, page_size: 1000 and enabled: true, on the grounds that "
            "EditDate is the source's own modification timestamp so no overlap "
            "window is needed. The authoritative returnCountOnly=true query is "
            "available on the layer. Rule on the proposal."
        ),
    },
    {
        "id": "src-10-lee-dev-activity-readback",
        "facts": {
            "arcgis": True,
            "count_mismatch": False,
            "source_count": 8841,
            "fetched_count": 8841,
            "proposes_event_date_cursor": False,
            "authoritative_count_available": True,
            "one_run_only": True,
        },
        "text": (
            "The first manual run of the Lee `dev-activity` dataset "
            "(pipeline/jurisdictions/lee.yaml, connector: arcgis, sync_mode: "
            "snapshot, id_field: GlobalID, cursor_field: OBJECTID) reports "
            "authoritative source count 8841, fetched 8841, lake 8841, published "
            "8841, unique GlobalIDs 8841, and a Parquet readback of 8841. No live "
            "readback of the status API or MCP health was performed, and no second "
            "manual run has been made. May scheduled ingestion be enabled for this "
            "dataset?"
        ),
    },
)


if __name__ == "__main__":  # a listing, so the file is runnable evidence
    for o in OBJECTIVES:
        print(f"{o['id']}\n  {o['text']}\n")
    print(f"{len(OBJECTIVES)} objectives")
