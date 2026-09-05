"""Owner checks on the harvested scenarios.

THREE rules, each written ONCE and applied to every scenario unchanged. Rules
2 and 3 carry a per-scenario VALUE, and that value is COMPUTED here from the
scenario's own objective and the persona's own stated thresholds — it is never
typed in by hand from reading an answer.

RULE 1 (shape). `working_memory.prompt_agent` must end with the verdict line
       the persona requires, in the form the persona spells out. The persona
       says "close with exactly one final line ... and nothing after it"; a
       reviewer whose ruling cannot be read by the thing that consumes it has
       not delivered a ruling.
       Disputable: a human reading the prose gets the answer either way, so an
       owner could call the format cosmetic.

RULE 2 (age). The day count ON THAT VERDICT LINE must be the age the objective
       states: floor(stated "Today is" date − the newest stated scrape_date),
       or `unknown` when the objective gives no scrape_date.
       Disputable, and this is the dispute an owner would actually have: the
       reviewer could be held right to prefer the real current date over the
       one the message states — in which case this check is wrong and the
       model is not.

RULE 3 (verdict token). The token on that line must be the one the persona's
       own thresholds entail: EXCLUDE if a stated price_per_mg_usd exceeds
       300 (rule 3 of the persona, `> 300`); else STALE if the age is unknown
       or >= STALE_AFTER_DAYS = 7; else FRESH.
       Disputable, and sharply: on the $299.98/mg BPC-157 row the model ruled
       EXCLUDE while stating in the same answer that the row clears the cap by
       two cents, reasoning from the cap's RATIONALE rather than its
       threshold. Many owners would call that the better answer. This check
       says the persona means `> 300` literally, because a reviewer that
       excludes rows the view keeps is describing a site that does not exist.

       The first draft of rule 2 was a `contains` over the whole answer, and it
       PASSED on all five — including the one whose verdict line carries the
       wrong number, because that answer discusses the right number in a
       caveat paragraph two lines above the wrong verdict. A control a long
       prose answer can satisfy by mentioning the answer somewhere is not a
       control. It is TIGHTENED here, never loosened, and this paragraph is
       the record of that.

DISCLOSURE, in ADR 0163's terms: the recorded answers were read before these
rules were written, to know whether a failure was reachable at all. All three
then come from the persona's own text and are applied unchanged to every
scenario.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
CORPUS = W / "peptide" / "corpus" / "train"

STALE_AFTER_DAYS = 7  # site/assets/js/kpi-format.js
CAP_PER_MG = 300.0  # db/price_outlier_cap_views.sql

VERDICT_RE = r"(?m)^VERDICT: (FRESH|STALE|EXCLUDE) [—-] .+, as of .+, .+ days old[ \t]*$"

TODAY_RE = re.compile(r"Today is (\d{4})-(\d{2})-(\d{2})")
SCRAPE_RE = re.compile(r"scrape_date (\d{4})-(\d{2})-(\d{2})")
PRICE_RE = re.compile(r"price_per_mg_usd (\d+(?:\.\d+)?)")


def age_days(objective: str) -> int | None:
    today = TODAY_RE.search(objective)
    scrapes = SCRAPE_RE.findall(objective)
    if not today or not scrapes:
        return None
    t = date(*(int(g) for g in today.groups()))
    newest = max(date(int(a), int(b), int(c)) for a, b, c in scrapes)
    return (t - newest).days


def expected_age_phrase(objective: str) -> str:
    days = age_days(objective)
    return "unknown days old" if days is None else f"{days} days old"


def expected_verdict(objective: str) -> str:
    prices = [float(p) for p in PRICE_RE.findall(objective)]
    if any(p > CAP_PER_MG for p in prices):
        return "EXCLUDE"
    days = age_days(objective)
    return "STALE" if days is None or days >= STALE_AFTER_DAYS else "FRESH"


for path in sorted(CORPUS.glob("*.json")):
    payload = json.loads(path.read_text())
    objective = payload["initial_state"]["objective"]
    age = expected_age_phrase(objective)
    verdict = expected_verdict(objective)
    checks = [
        {"path": "working_memory.prompt_agent", "op": "regex", "value": VERDICT_RE},
        {
            "path": "working_memory.prompt_agent",
            "op": "regex",
            "value": r"(?m)^VERDICT: .*, " + re.escape(age) + r"[ \t]*$",
        },
        {
            "path": "working_memory.prompt_agent",
            "op": "regex",
            "value": r"(?m)^VERDICT: " + verdict + r" [—-] ",
        },
    ]
    payload["checks"] = checks
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    reread = json.loads(path.read_text())
    assert reread["checks"] == checks, f"patch did not take on {path.name}"
    prices = [float(p) for p in PRICE_RE.findall(objective)]
    print(f"{path.name[:8]}  expected: {verdict:<7} {age:<16} "
          f"(age_days={age_days(objective)}, max stated $/mg={max(prices) if prices else None})")

print(f"\n{len(list(CORPUS.glob('*.json')))} scenario(s) now carry 3 owner check(s) each.")
