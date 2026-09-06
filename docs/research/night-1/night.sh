#!/bin/zsh
# The unattended night (ADR 0200, part C).
#
# Started once, and then left. Nothing in this script asks a human anything,
# nothing reads its own output and decides, and nothing after the `aef loop
# run` line can change what that line did. The post-run commands are the
# MORNING REPORT's raw material — a digest, the lineage, the ledger, the
# journal — produced by the job itself so that what a person reads at 09:00 is
# what the job left behind rather than what someone typed afterwards.
#
# It is SCHEDULED in the only sense available on one machine: it waits for a
# wall-clock instant it does not choose and then fires. That is the same
# property `cron` gives the workflow, minus the daemon.
set -uo pipefail

P=/private/tmp/claude-501/-Users-raptor-aef-core/8b1c008a-2030-4e1d-88fe-224f5c867a6e/scratchpad/w/p1
N=$P/night
export PATH=/Users/raptor/aef-core/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin
export PYTHONPATH=/Users/raptor/aef-core/.claude/worktrees/agent-a6db367f8d61f9cc2

FIRE_AT=${1:?usage: night.sh <epoch-seconds to fire at>}

{
  echo "scheduled for : $(date -u -r "$FIRE_AT" '+%Y-%m-%dT%H:%M:%SZ')"
  echo "started at    : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "waiting       : $((FIRE_AT - $(date +%s)))s"
} | tee $N/10-schedule.txt

while [ "$(date +%s)" -lt "$FIRE_AT" ]; do
  sleep 1
done
echo "fired at      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')" | tee -a $N/10-schedule.txt

cd $P/pilot || exit 9

# The night itself. `timeout` is this job's OWN guard, not a supervisor: if it
# fires, the night overran its window and that is the night's result.
start=$(date +%s)
# `timeout(1)` does not exist on macOS — the first attempt at this night
# died at exit 127 before the loop ran at all, which is recorded rather
# than tidied away. `perl -e alarm` is the portable equivalent.
perl -e 'alarm shift; exec @ARGV' 470 aef loop run \
  --repo $P/pilot --state $P/state \
  --workdir $N/wd \
  --module agents/migrated/price_freshness_reviewer/graph.py:build_graph \
  --entrypoint agents/migrated/price_freshness_reviewer/graph.py:build_graph \
  --runs $P/runs \
  --corpus $P/pilot/corpus \
  --proposer rule_based_prompt \
  --agent-root .claude/agents \
  --agent-path .claude/agents/price-freshness-reviewer.md \
  --memory $P/state/memory.jsonl \
  --config aef.yaml \
  --cassette-miss live \
  --build-command "python -c pass" \
  --candidates 2 \
  --audit-slice 1 \
  --turns 3 \
  --budget-minutes 3 \
  > $N/11-run.txt 2>&1
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
    142) echo "meaning          : the night's own 470s alarm fired (SIGALRM) — it overran" ;;
    *) echo "meaning          : exit $rc is not a code this loop defines" ;;
  esac
} | tee $N/12-exit.txt

# --- what a person reads in the morning, produced by the job -----------------

aef loop status --repo $P/pilot --state $P/state   > $N/13-status.txt 2>&1
aef loop digest --repo $P/pilot --state $P/state --runs $P/runs > $N/14-digest.txt 2>&1
aef loop monitor --repo $P/pilot --state $P/state  > $N/15-monitor.txt 2>&1
aef loop lineage list --repo $P/pilot --state $P/state > $N/16-lineage.txt 2>&1
cp $P/state/ledger.jsonl $N/17-ledger.jsonl 2>/dev/null
cp $P/state/cycles.jsonl $N/18-cycles.jsonl 2>/dev/null
git -C $P/pilot branch --list > $N/19-branches.txt 2>&1
git -C $P/pilot log --oneline -3 master > $N/20-master-after.txt 2>&1
{
  echo "--- halt channel log ---"
  cat $N/HALT-CHANNEL.log 2>/dev/null || echo "(the channel never fired — no file)"
} > $N/21-halt-channel.txt 2>&1
git -C $P/pilot diff master loop/kept -- .claude/agents > $N/22-kept-diff.txt 2>&1

echo "finished at   : $(date -u '+%Y-%m-%dT%H:%M:%SZ')" | tee -a $N/10-schedule.txt
exit $rc
