#!/bin/zsh
# The unattended night on marlin (ADR 0204 step 5).
#
# Started once, and then left. Nothing in this script asks a human anything,
# nothing reads its own output and decides, and nothing after the `aef loop
# run` line can change what that line did. The post-run commands are the
# MORNING REPORT's raw material — the status, the digest, the monitor, the
# lineage, the ledger — produced by the job itself, so what a person reads
# afterwards is what the job left behind rather than what someone typed.
#
# It is SCHEDULED in the only sense available on one machine: it waits for a
# wall-clock instant it does not choose and then fires.
#
# SIZING, from `15-live-miss-probe.txt` and not from a guess: a live call on
# this repo's answers costs 27 s, a turn costs 6 x (gated scenarios) live
# calls, and the harness this runs under caps a foreground step at 600 s. So
# `--audit-slice 2` (3 gated of 5) puts one turn at ~18 calls / ~490 s, and
# `--budget-minutes 3` is what makes the driver STOP rather than start a turn
# it cannot finish. The alarm is this job's own guard, not a supervisor: if it
# fires, the night overran and that is the night's result.
set -uo pipefail

Q=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/q1
N=$Q/night
# ATTEMPT 3 (recorded, not tidied away): this line lacked ~/.local/bin, so the
# gates' worker could not FIND the `claude` binary. Every candidate scenario
# raised, and the ledger reported it as `G2 rejected it: 3 previously-passing
# scenario(s) no longer pass` — a verdict about the prompt (F-Q1-5). My
# harness, not the loop; the loop's part is that the cause did not reach the
# ledger. `aef loop score` on the same tree names it on every scenario:
#   raised: ModelProviderError: harness executable not found: 'claude'
export PATH=/Users/raptor/aef-core/.venv/bin:/Users/raptor/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export PYTHONPATH=/Users/raptor/aef-core/.claude/worktrees/agent-a1aa5766514609859:$Q/marlin

FIRE_AT=${1:?usage: night.sh <epoch-seconds to fire at>}
WD=$N/wd-$(date +%s)   # ATTEMPT 2 reused $N/wd and every gate became a
mkdir -p $WD          # TrustBoundaryError (F-Q1-4). A run's workdir is single-use.

{
  echo "scheduled for : $(date -u -r "$FIRE_AT" '+%Y-%m-%dT%H:%M:%SZ')"
  echo "started at    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "waiting       : $((FIRE_AT - $(date +%s)))s"
} | tee $N/20-schedule.txt

while [ "$(date +%s)" -lt "$FIRE_AT" ]; do
  sleep 1
done
echo "fired at      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')" | tee -a $N/20-schedule.txt

cd $Q/marlin || exit 9

# ATTEMPT 1 (recorded, not tidied away): this line was absent, and the night
# proposed twice and was rejected twice by G5 with "no owner-blessed baseline
# to measure drift against ... Create one with `aef loop bless`" — after
# `bless --graph-id marlin-source` had succeeded and `doctor --graph-id
# marlin-source` reported `[OK] blessed baseline  1 archived version(s)`.
# `bless` archived under `archive/marlin-source/`; `run` without --graph-id
# derives the EVIDENCE id from the corpus but leaves the ARCHIVE KEY at
# 'default' (ADR 0182), so G5 looked in a directory that does not exist.
# F-Q1-3. The flag below is the operator-side fix.
# ATTEMPT 4: the alarm was 540 s and it FIRED mid-gate — the ledger held
# `proposed` and no `gated`. Measured afterwards rather than guessed: copying
# the 185 MB worktree seven times costs 0.6 s per copy on APFS, so the turn is
# model time — 18 live calls (6 x 3 gated) at ~30 s. 580 s is the most this
# harness's 600 s foreground cap allows once the 3 s wait and the post-run
# reporting commands are paid for.
# ATTEMPT 5: the 580 s alarm fired too. `resplit.py` then moved two PASSING
# scenarios to validation — train 5 -> 3 — because `audit_slice` caps its draw
# at half the train split, so 5 in train cannot be gated on fewer than 3.
# With 3 in train and --audit-slice 1 today's draw holds back a9c8ba03 and
# gates 2, which is 12 live calls. What that costs is in resplit.py's
# docstring and in the morning report: neither gated scenario is one the
# incumbent passes, so G2 has nothing to protect.
# ATTEMPT 6 ran clean and G3 REFUSED TO JUDGE: `4 dead call(s) of 4
# scenario(s) (100%), over the 25% ceiling` (ADR 0185) — the operator's quota
# had run out mid-night, so the model was not answering. The refusal is the
# gate working: neither a pass nor a rejection would have been about the
# candidate. Its ledger line also corrected the sizing arithmetic: `4/4 gated
# scenario(s) ... 1 held back` on a corpus of 5 with a train split of 3, so
# GATED = corpus - audit slice, and the resplit that shrank train had made the
# turn dearer, not cheaper. Restored to 5 in train; --audit-slice 2 draws 2 and
# gates 3 = 18 live calls.
start=$(date +%s)
# `timeout(1)` does not exist on macOS; `perl -e alarm` is the portable form.
perl -e 'alarm shift; exec @ARGV' 580 python -m aef.cli.main loop run \
  --repo $Q/marlin --state $Q/state \
  --graph-id marlin-source \
  --workdir $WD \
  --module agents.migrated.marlin_source.graph \
  --entrypoint agents.migrated.marlin_source.graph:build_graph \
  --runs $Q/runs \
  --corpus corpus \
  --proposer rule_based_prompt \
  --agent-root .claude/agents \
  --agent-path .claude/agents/source-agent.md \
  --memory $Q/state/memory.jsonl \
  --config aef.yaml \
  --cassette-miss live \
  --build-command "python -c pass" \
  --candidates 2 \
  --audit-slice 2 \
  --turns 3 \
  --budget-minutes 3 \
  > $N/21-run.txt 2>&1
rc=$?
end=$(date +%s)

{
  echo "aef loop run exit: $rc"
  echo "wall clock       : $((end - start))s"
  case "$rc" in
    0) echo "meaning          : the run completed; read the per-turn verdicts" ;;
    1) echo "meaning          : REJECTED by a gate — the system working" ;;
    2) echo "meaning          : HALTED — the kill switch is on" ;;
    3) echo "meaning          : ERROR — the run crashed; fix the invocation" ;;
    142) echo "meaning        : the night's own 580s alarm fired (SIGALRM) — it overran" ;;
    *) echo "meaning          : exit $rc is not a code this loop defines" ;;
  esac
} | tee $N/22-exit.txt

# --- what a person reads afterwards, produced by the job ---------------------

python -m aef.cli.main loop status  --repo $Q/marlin --state $Q/state > $N/23-status.txt 2>&1
python -m aef.cli.main loop digest  --repo $Q/marlin --state $Q/state --runs $Q/runs > $N/24-digest.txt 2>&1
python -m aef.cli.main loop monitor --repo $Q/marlin --state $Q/state > $N/25-monitor.txt 2>&1
python -m aef.cli.main loop lineage list --repo $Q/marlin --state $Q/state > $N/26-lineage.txt 2>&1
cp $Q/state/ledger.jsonl $N/27-ledger.jsonl 2>/dev/null
cp $Q/state/cycles.jsonl $N/28-cycles.jsonl 2>/dev/null
git -C $Q/marlin branch --list        > $N/29-branches.txt 2>&1
git -C $Q/marlin log --oneline -3 main > $N/30-main-after.txt 2>&1
{
  echo "--- halt channel log ---"
  cat $N/HALT-CHANNEL.log 2>/dev/null || echo "(the channel never fired — no file)"
} > $N/31-halt-channel.txt 2>&1
git -C $Q/marlin diff main loop/kept -- .claude/agents > $N/32-kept-diff.txt 2>&1

echo "finished at   : $(date -u '+%Y-%m-%dT%H:%M:%SZ')" | tee -a $N/20-schedule.txt
exit $rc
