#!/usr/bin/env python
"""Quota preflight, ADR 0150's corrected argv — one call, before anything else.

Runs the SAME argv `ClaudeCodeProvider` builds (it asks the provider for it,
rather than restating the flags, so a preflight cannot pass while the flags
the measurement uses are different), and writes the CLI's raw JSON to
`preflight.json`. `modelUsage` in that payload is where every claim in ADR
0162 about which model answered begins.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aef.providers.base import CompletionRequest, ProviderMessage  # noqa: E402
from aef.providers.harness_provider import ClaudeCodeProvider  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else ""
    out = HERE / (f"preflight-{model}.json" if model else "preflight.json")
    provider = ClaudeCodeProvider(default_model=model or None)
    request = CompletionRequest(
        messages=(
            ProviderMessage(role="system", content="Reply with OK and nothing else."),
            ProviderMessage(role="user", content="Say OK."),
        ),
        model=model,
        max_tokens=16,
    )
    argv = provider.argv(request)
    print(" ".join(repr(a) for a in argv))
    run = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    print(f"returncode {run.returncode}")
    payload = json.loads(run.stdout)
    out.write_text(json.dumps(payload, sort_keys=True) + "\n")
    print(
        f"is_error={payload.get('is_error')} result={payload.get('result')!r} "
        f"input_tokens={(payload.get('usage') or {}).get('input_tokens')}"
    )
    print("modelUsage keys:", sorted((payload.get("modelUsage") or {}).keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
