# ADR 0195: A halt that reaches someone

## Status
Accepted. Worker **N4** of the above-95 loop, closing the second half of ADR 0188's dimension-4 deduction (15 → 13).

## Context

J0b's second dimension-4 finding was one sentence, and it quoted the system
against itself:

> "a shipped hole the system admits itself: `aef loop digest` printed
> `Halt channel configured: NO`."

The line was accurate. Reproduced before anything was changed — engage the
kill switch, run a halt, look:

```
kill switch engaged  : True
ledger HALTED entries: ['halted']
halt entry detail    : {'reasons': ['a gated change regressed live']}
external file exists : False
digest> - Halts: 1
digest> - Halt channel configured: NO
```

The loop halted, correctly, wrote `HALT.md` into a checkout nobody was looking
at, appended a tamper-evident ledger entry nobody was reading, and **told no
one**. `05-approval-policy.md` §7 says explicitly that a halt must not depend
on someone reading GitHub email; a halt that depends on someone noticing the
loop stopped is worse than that.

There was a `HaltNotifier` with a `webhook_url` field, and reading it closely
is what makes the old line's meaning precise. **Nothing in `aef/` ever called
`notify`.** The URL came from `AEF_HALT_WEBHOOK`, which no workflow set. So
`Halt channel configured: NO` was not "the owner declined to configure it"; it
was "there is nothing an owner could configure and have run" — the ADR 0100
shape, in the one surface whose whole job is to say when something has gone
wrong.

## Decision

**`halt_channel:` in `aef.yaml` — an argv template, the same shape as
`model_provider.impl: command`** (ADR 0154), and for the same reason. This
repo does not know how its owner is paged. It ships no webhook client, no SDK,
no new dependency and no guess: the owner writes the command, and what that
command reaches is the owner's business.

```yaml
halt_channel:
  argv: ["/usr/bin/logger", "-t", "aef", "{reason}"]
  timeout_s: 30.0
```

Six decisions inside that, each of which could have gone the other way:

**`{reason}` is a slot, and the payload goes on stdin.** The slot is optional;
the JSON object on stdin always carries the reason, the timestamp, and **the
ledger's last entry** — which is what says *which* candidate and *when*,
without the reader opening the ledger. A channel that wants everything reads
stdin; a channel that wants a subject line uses the slot.

**Read from the BASE REF**, like every other rule a candidate is judged by
(ADR 0082, ADR 0181). The halt most worth delivering is, by construction, the
one a candidate caused: a rollback of a change *every gate passed* halts the
loop because the gates have a blind spot. A channel a candidate could delete on
its own branch is one it would. This is A18 in the red-team suite (ADR 0194),
with its mutation: resolve from the working tree instead — the natural first
draft, since the file is right there — and the candidate's deletion silences
its own halt while the loop still halts and reports nothing wrong.

**One resolver for the halt and the digest.** `_halt_channel(config)` is
called by both, and that is the entire reason it is a function. A digest
printing `Halt channel configured: yes` while a halt found nothing to run
would be the same class of defect as the line this ADR removes, one level up
and harder to notice.

**The kill switch is engaged BEFORE the channel runs.** A channel that takes
its whole timeout must not leave a window in which the loop is still runnable.
Asserted by a test that records the switch's state from inside the runner.

**Every failure of the channel is recorded and none of them masks the halt.**
`HaltChannel.notify` converts a missing program, a non-zero exit and a timeout
into a `HaltNotification` rather than raising; `_halt_channel` returns `None`
for a missing, absent or unloadable config rather than raising. A malformed
`aef.yaml` must not be able to stop a halt from being recorded — the halt
matters more than the notification. Reproduced on a channel that cannot start:

```
halt entry detail : {'halt_notification': {'at': '2026-09-05T03:00:00+00:00',
  'command': '/bin/false', 'delivered': False, 'detail': "FileNotFoundError:
  [Errno 2] No such file or directory: '/bin/false'; the halt still stands"},
  'reasons': ['a gated change regressed live']}
digest> - Halt channel configured: yes — /bin/false (0 argument(s))
digest> - 2026-09-05T03:00:00+00:00 FAILED: /bin/false — FileNotFoundError: …
digest>   **A halt notification FAILED.** The halt still stands; what did not
digest>   happen is you being told about it. Fix the command, not the loop.
```

**`argv[0]` only, in the ledger and in the digest.** The rest of an owner's
command line is where a token ends up when somebody writes one there, and the
ledger is committed evidence. The digest prints `"/bin/sh (2 argument(s))"`.

## Reproduced, both ways, with the test channel the brief named

`/bin/sh -c 'cat >> file'` — a real subprocess, no network anywhere in this
work. After the change, on the same fixture as the `NO` transcript above:

```
=== B: halt_channel naming /bin/sh -c 'cat >> file' ===
kill switch engaged  : True
halt entry detail    : {'halt_notification': {'at': '2026-09-05T03:00:00+00:00',
  'command': '/bin/sh', 'delivered': True, 'detail': 'exit 0'},
  'reasons': ['a gated change regressed live']}
external file exists : True
external file content: '{"at": "2026-09-05T03:00:00+00:00", "event": "halt",
  "last_ledger_entry": null, "reason": "a gated change regressed live"}'
digest> - Halt channel configured: yes — /bin/sh (2 argument(s))
```

And the unconfigured case is no longer merely a `NO`. The digest now reads the
ledger's own `HALTED` entries, so a halt that reached nobody says so in the
place an owner is already looking:

```
digest> - Halt channel configured: NO
digest> **No halt channel is configured.** … Name a command in `halt_channel:`
digest> - 2026-09-05T03:00:00+00:00 NOT SENT: no halt channel was configured
        when the loop halted
```

Reading the notifications from the LEDGER rather than from a parameter is
deliberate: the process that halted is long gone by the time anyone runs
`digest`, and a channel that is configured and **failing** looks identical,
from the config alone, to one that works.

## What this does NOT do

Stated here because the alternative is an owner believing they are covered.

- **It does not retry.** A channel that retried would be a queue, and a queue
  that loses its process loses the message anyway. The durable record is the
  ledger; this is the doorbell.
- **It does not page anyone by itself.** It runs a command. Whether that
  command reaches a human — SMS, PagerDuty, `logger`, a webhook via `curl` —
  is the command's business, and this repo ships no opinion about it.
- **It is exactly as reliable as the command the owner wrote.** `delivered` is
  the process's exit status. It is named after the thing this code can
  observe, and it is not "the owner saw it".
- **It is not queued, batched or rate-limited.** One halt, one invocation.
- **It does not remove the webhook path.** `HaltNotifier` still posts to
  `AEF_HALT_WEBHOOK` when one is set, and now runs both channels rather than
  either — a webhook that throws no longer skips the command channel.

## What would earn the rest of dimension 4

The point this closes is a hole the system admitted about itself. What it does
not close, and what a future reviewer should ask for:

1. **A halt channel that has fired in anger.** Every transcript here is a
   constructed halt. The channel has never been invoked by a real regression on
   a real repo, and until it has, "the owner would be told" is a property of
   the code rather than of the deployment.
2. **`aef loop digest --config`.** The digest resolves the channel through
   `DEFAULT_CONFIG_PATH` (`aef.yaml` at the base ref) when the invocation names
   none, because `aef loop digest` takes no `--config` flag today and the
   command whose whole job is to say whether a channel exists must be able to
   see it. That default is documented rather than guessed — `aef adopt` writes
   `aef.yaml`, and the onboarding kit names it — but an explicit flag would be
   better than a convention, and adding one is a CLI change this worker did not
   own.
3. **Delivery evidence beyond an exit code**, for a channel where that is
   meaningful.

## Consequences

`aef loop digest` can still print `Halt channel configured: NO`, and that is
correct: it means the owner has not named a command. What it can no longer
mean is that there was nothing to name. The line changed from an admission
about the system into a fact about the configuration.

+26 tests (`tests/harness/test_halt_channel.py`) and +4 in the red-team suite
(A18). One new schema block, one factory function, one resolver, and the halt
site in `aef/harness/loop.py`. No existing test changed.
