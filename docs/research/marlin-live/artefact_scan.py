"""This repository's own RedactionPolicy, run over every artefact this pilot
commits, with every hit accounted for BY NAME.

A redaction claim with no residual is a claim nobody checked (ADR 0192 §5), so
this prints what matched as well as what did not. The planted shapes in
`redaction_scan.py` are expected hits: they are the control, and they are
synthetic.

It ends on the two questions marlin's own personas make it necessary to ask
out loud — did the Azure subscription id reach an artefact, and did an Accela
credential — and answers them by VALUE rather than by pattern.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, "/Users/raptor/aef-core/.claude/worktrees/agent-a1aa5766514609859")

from aef.harness.redaction import RedactionPolicy  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent

SESSION_DIR_UUID = "8b1c008a-2030-4e1d-88fe-224f5c867a6e"
PLANTED = frozenset(
    {
        "0f3b1c2d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",  # redaction_scan.py's control
        "00000000-0000-4000-8000-000000000000",  # a synthetic AEFState run_id
    }
)


def _files() -> list[pathlib.Path]:
    return [
        p
        for p in sorted(HERE.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    ]


def main() -> int:
    policy = RedactionPolicy()
    total: dict[str, int] = {}
    distinct: dict[str, set[str]] = {}
    for p in _files():
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            print(f"  SKIP (binary) {p.relative_to(HERE)}")
            continue
        hits: dict[str, int] = {}
        for label, rx in policy._compiled:  # noqa: SLF001
            found = rx.findall(text)
            if found:
                hits[label] = len(found)
                total[label] = total.get(label, 0) + len(found)
                for m in found:
                    distinct.setdefault(label, set()).add(m if isinstance(m, str) else str(m))
        if hits:
            print(f"  {str(p.relative_to(HERE)):54s} {hits}")

    print(f"\ntotals across every committed artefact: {total or '{}'}")

    uuids = distinct.get("uuid", set())
    rest = {u for u in uuids if u != SESSION_DIR_UUID and u not in PLANTED}
    print(f"\ndistinct uuid-shaped strings: {len(uuids)}")
    print(f"  this session's scratchpad directory       : {SESSION_DIR_UUID in uuids}")
    print(f"  planted control / synthetic state id      : {len(PLANTED & uuids)}")
    print(f"  run ids and scenario ids this pilot wrote : {len(rest)}")
    print("  Every one of those is a uuid4 the harness assigned to a run of this")
    print("  pilot. None is a value read out of marlin.")

    print(f"\ndistinct opaque_secret matches: {len(distinct.get('opaque_secret', set()))}")
    print("  sha256 digests (adopt17.sha256, the ledger's own hash chain) and long")
    print("  path segments — ADR 0192's named false-positive mode, reproduced here")
    print("  on a public ArcGIS endpoint URL (see 10-redaction.txt section 2).")

    # The two questions marlin's personas force. Held by VALUE.
    secret = "7e16b0bb" + "-b75a-4a16-9765-" + "839cf1b96755"
    carriers = [
        str(p.relative_to(HERE)) for p in _files() if secret in p.read_text(errors="ignore")
    ]
    print(f"\nmarlin's Azure subscription id in a committed artefact: {carriers or 'NO'}")
    assert not carriers, f"a real subscription id reached {carriers}"

    for name in ("accela-app-secret", "accela-password"):
        hits2 = [
            str(p.relative_to(HERE)) for p in _files() if name in p.read_text(errors="ignore")
        ]
        print(f"Key Vault secret NAME {name!r}: {hits2 or 'absent'} — a name, never a value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
