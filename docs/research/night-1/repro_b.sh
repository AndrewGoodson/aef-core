#!/bin/zsh
# B: reproduce — nothing automated reads the holdout.
set -uo pipefail
R=/Users/raptor/aef-core/.claude/worktrees/agent-a6db367f8d61f9cc2
cd "$R" || exit 1
export PYTHONPATH="$R"
export PATH=/Users/raptor/aef-core/.venv/bin:$PATH

echo "== 1. who reads the holdout at all"
grep -rn "i_am_spending_the_holdout\|i-am-spending-the-holdout" aef/ | sed 's/^/   /'

echo
echo "== 2. every SCHEDULED surface, and whether it names the holdout"
for f in .github/workflows/*.yml; do
  n=$(grep -c "holdout" "$f")
  echo "   $f: holdout mentioned $n time(s)"
done
echo -n "   aef/cli/adopt_loop.py rendered nightly: "
python - <<'PY'
import re, pathlib
src = pathlib.Path("aef/cli/adopt_loop.py").read_text()
# every rendered workflow/cron body in the adopter template
hits = src.count("i-am-spending-the-holdout")
print(f"'--i-am-spending-the-holdout' appears {hits} time(s) in anything it renders")
PY

echo
echo "== 3. the refusal, run"
aef loop score agents.demo.graph --corpus corpus --splits holdout 2>&1 | sed 's/^/   /'
echo "   exit=${pipestatus[1]}"

echo
echo "== 4. what the holdout contains"
ls corpus/holdout | sed 's/^/   /'
