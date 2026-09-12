set -euo pipefail
mkdir -p "$HOME/.aef-loop-state"
# No credentials, Docker socket, or writable source mount crosses here.
# Failure to start this isolated container fails the job; no host fallback.
docker run --rm --pull never --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,exec,mode=1777 --tmpfs /work:rw,exec,mode=1777 \
  --mount "type=bind,src=$AEF_GATE_ROOT/repo,dst=/repo,readonly" \
  --mount "type=bind,src=$HOME/.aef-loop-state,dst=/state" \
  --workdir /repo --env HOME=/tmp "$AEF_GATE_IMAGE" \
  aef loop gate --repo /repo --state /state \
  --base main --head refs/loop/candidate \
  --workdir /work/gate --corpus /repo/corpus \
  --graph-id demo_agent --agent-path agents/demo/graph.py \
  --entrypoint "$AEF_ENTRYPOINT" \
  --build-command "$AEF_BUILD_COMMAND" \
  --network-isolated
