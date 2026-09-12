set -euo pipefail
mkdir "$AEF_GATE_ROOT"
mkdir -p "$AEF_GATE_ROOT/image/source"
git archive refs/heads/main | tar -x -C "$AEF_GATE_ROOT/image/source"
cat > "$AEF_GATE_ROOT/image/Dockerfile" <<'DOCKERFILE'
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY source /opt/aef-base
RUN pip install "/opt/aef-base[dev]"
DOCKERFILE
# Network is available for trusted dependency preparation only.
docker build --tag "$AEF_GATE_IMAGE" "$AEF_GATE_ROOT/image"
