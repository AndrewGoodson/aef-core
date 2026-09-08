"""Move two PASSING harvested scenarios from TRAIN to VALIDATION.

**This is a wall-clock decision and it is disclosed as one.** A turn costs
6 x (gated scenarios) live calls at ~30 s; the harness this pilot runs under
caps one foreground step at 600 s; and `audit_slice` caps its own draw at half
the train split, so a 5-scenario train split cannot be gated on fewer than 3
scenarios (18 calls, ~560 s) — measured twice, by two nights that overran a
540 s and a 580 s alarm mid-gate with `proposed` in the ledger and no `gated`.

With three in train, today's draw (a function of the sorted ids and the date,
which nothing here chose) holds back `a9c8ba03` and gates `9305e905` and
`a62dfb48` — 12 calls, ~360 s.

WHAT IT COSTS, stated because it is the weakness of the night that follows:
both gated scenarios are ones the incumbent FAILS, so G2 — "no previously-
passing scenario may stop passing" — has nothing to protect and passes
vacuously. The verdict rests on G3 alone.

WHAT IT DOES NOT COST: no evidence. Both scenarios moved are ones the
incumbent scores 1.0000 on, so neither carries a check-derived failure record,
and `MemoryEvidence`'s refusal of validation records removes nothing the
proposer was using.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

MOVE = ("2b1b3501", "48572a57")


def _restore(corpus: pathlib.Path, train: pathlib.Path, validation: pathlib.Path) -> int:
    """Undo the move — REVERTED, because the inference behind it was wrong.

    The night's own ledger line reads `4/4 gated scenario(s) ... 1 held back
    for the audit`, on a corpus of 5 with a train split of 3. So the GATED set
    is the whole corpus minus the audit slice, not the train split: moving a
    scenario to validation removes it from the proposer's evidence and from
    the slice's pool while leaving it gated, which made the turn MORE
    expensive (train 3 caps the draw at 1, so 5 - 1 = 4 gated) rather than
    less. Restoring all five to train and drawing 2 gives 3 gated.
    """
    moved = 0
    for p in sorted(validation.glob("*.json")):
        if not p.name.startswith(MOVE):
            continue
        d = json.loads(p.read_text())
        assert d["split"] == "validation", f"{p.name} is not in the validation split"
        d["split"] = "train"
        dest = train / p.name
        dest.write_text(json.dumps(d, indent=1))
        p.unlink()
        assert json.loads(dest.read_text())["split"] == "train", "patch did not take"
        print(f"restored {p.name[:8]} validation -> train")
        moved += 1
    assert moved == len(MOVE), f"expected to restore {len(MOVE)}, restored {moved}"
    manifest = corpus / "manifest.json"
    m = json.loads(manifest.read_text())
    for k in list(m["scenarios"]):
        if k.startswith(MOVE):
            m["scenarios"][k] = "train"
    manifest.write_text(json.dumps(m, indent=2))
    assert all(v == "train" for v in json.loads(manifest.read_text())["scenarios"].values())
    print(f"{moved} scenario(s) restored; manifest rewritten")
    return 0


def main() -> int:
    corpus = pathlib.Path(sys.argv[1])
    restore = "--restore" in sys.argv
    train, validation = corpus / "train", corpus / "validation"
    if restore:
        return _restore(corpus, train, validation)
    validation.mkdir(exist_ok=True)
    moved = 0
    for p in sorted(train.glob("*.json")):
        if not p.name.startswith(MOVE):
            continue
        d = json.loads(p.read_text())
        assert d["split"] == "train", f"{p.name} is not in the train split"
        d["split"] = "validation"
        dest = validation / p.name
        dest.write_text(json.dumps(d, indent=1))
        p.unlink()
        assert json.loads(dest.read_text())["split"] == "validation", "patch did not take"
        print(f"moved {p.name[:8]} train -> validation")
        moved += 1
    assert moved == len(MOVE), f"expected to move {len(MOVE)}, moved {moved}"
    # the manifest is rewritten by the next command that saves a scenario; make
    # the corpus self-consistent now so `load_corpus` sees the new splits.
    manifest = corpus / "manifest.json"
    if manifest.exists():
        shutil.copy(manifest, corpus / "manifest.json.bak")
    print(f"{moved} scenario(s) moved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
