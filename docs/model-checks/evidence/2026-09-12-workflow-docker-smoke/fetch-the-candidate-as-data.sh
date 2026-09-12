set -euo pipefail
git check-ref-format "refs/heads/$AEF_CANDIDATE_REF"
git fetch --no-tags origin "refs/heads/$AEF_CANDIDATE_REF:refs/loop/candidate"
# A fresh repo transfers objects and refs, not credentials or hooks.
git init --initial-branch=gate-preparation "$AEF_GATE_ROOT/repo"
git -C "$AEF_GATE_ROOT/repo" fetch --no-tags "$GITHUB_WORKSPACE" \
  refs/heads/main:refs/heads/main refs/loop/candidate:refs/loop/candidate
git -C "$AEF_GATE_ROOT/repo" checkout main
