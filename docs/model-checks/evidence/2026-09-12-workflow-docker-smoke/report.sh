# Use the same installed trusted runtime, never host imports.
docker run --rm --pull never --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,exec,mode=1777 \
  --mount "type=bind,src=$AEF_GATE_ROOT/repo,dst=/repo,readonly" \
  --mount "type=bind,src=$HOME/.aef-loop-state,dst=/state,readonly" \
  --workdir /repo --env HOME=/tmp "$AEF_GATE_IMAGE" \
  aef loop status --repo /repo --state /state || true
