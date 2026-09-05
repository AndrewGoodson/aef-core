"""Run BOTH redaction policies over N7's own committed artefacts before they
are committed:

  * the policy on this branch's base (`d8357c2`) — email, api_key, bearer,
    aws_key, opaque_secret; and
  * the policy on the trunk, which gained connection_string, jwt,
    github_token, slack_token and **uuid** an hour after this pilot's §5 named
    the UUID as its residual (ADR 0197, worker N5).

The second is the one that binds, because this branch merges into that trunk.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from aef.harness.redaction import DEFAULT_PATTERNS as BASE_PATTERNS
from aef.harness.redaction import RedactionPolicy

W = Path(
    "/private/tmp/claude-501/-Users-raptor-aef-core/"
    "8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/n7"
)
ART = Path(
    "/Users/raptor/aef-core/.claude/worktrees/agent-a55b5aa3dfc315f8b/docs/research/pilot-peptide"
)

spec = importlib.util.spec_from_file_location("redaction_trunk", W / "redaction_main.py")
assert spec and spec.loader
trunk_mod = importlib.util.module_from_spec(spec)
sys.modules['redaction_trunk'] = trunk_mod
spec.loader.exec_module(trunk_mod)
TRUNK_PATTERNS = trunk_mod.DEFAULT_PATTERNS

BASE = RedactionPolicy(patterns=BASE_PATTERNS)
TRUNK = RedactionPolicy(patterns=TRUNK_PATTERNS)

print(f"base  policy ({len(BASE_PATTERNS)} patterns): {', '.join(x for x, _ in BASE_PATTERNS)}")
print(f"trunk policy ({len(TRUNK_PATTERNS)} patterns): {', '.join(x for x, _ in TRUNK_PATTERNS)}")
files = sorted(f for f in ART.iterdir() if f.is_file())
print(f"{len(files)} artefact file(s) scanned in {ART.name}/")
print()

for name, policy in (("BASE (this branch's aef/)", BASE), ("TRUNK (ADR 0197)", TRUNK)):
    print(f"== {name}")
    hits = []
    for f in files:
        labels = policy.find(f.read_text(errors="replace"))
        if labels:
            hits.append((f.name, labels))
    if not hits:
        print("   0 file(s) match.")
    for fn, labels in hits:
        print(f"   {fn}: {sorted(labels)}")
    print()

print("== every match, named, so a zero and a known-benign hit are told apart")
uuid_re = re.compile(dict(TRUNK_PATTERNS)["uuid"])
opaque_re = re.compile(dict(TRUNK_PATTERNS)["opaque_secret"])
api_re = re.compile(dict(TRUNK_PATTERNS)["api_key"])
email_re = re.compile(dict(TRUNK_PATTERNS)["email"])
uuids: set[str] = set()
opaques: set[str] = set()
apis: set[str] = set()
emails: set[str] = set()
for f in files:
    text = f.read_text(errors="replace")
    uuids |= set(uuid_re.findall(text))
    opaques |= set(opaque_re.findall(text))
    apis |= set(api_re.findall(text))
    emails |= set(email_re.findall(text))
print(f"   distinct uuid matches          : {len(uuids)}")
print(f"   distinct opaque_secret matches : {len(opaques)} -> {sorted(opaques)}")
print(f"   distinct api_key matches       : {len(apis)} -> {sorted(apis)}")
print(f"   distinct email matches         : {len(emails)} -> {sorted(emails)}")
