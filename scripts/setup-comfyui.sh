#!/usr/bin/env bash
# Provision a throwaway ComfyUI checkout with a CPU-only venv for
# integration testing. Used by CI (ci.yml, compat.yml) and locally.
#
# Usage: setup-comfyui.sh <target-dir> [ref]
#   ref: git branch or tag (default: master), or "latest-release" to
#        resolve the newest GitHub release tag.
#
# Prints the venv python path; export it as COMFYUI_PYTHON (the test
# harness also finds <dir>/.venv/bin/python on its own).
set -euo pipefail

DIR="${1:?usage: setup-comfyui.sh <target-dir> [ref]}"
REF="${2:-master}"
REPO="https://github.com/comfyanonymous/ComfyUI"

if [[ "$REF" == "latest-release" ]]; then
    REF=$(curl -fsSL https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
    echo "Resolved latest release: $REF"
fi

if [[ -d "$DIR/.git" ]]; then
    git -C "$DIR" fetch --depth 1 origin "$REF"
    git -C "$DIR" checkout --detach FETCH_HEAD
else
    git clone --depth 1 --branch "$REF" "$REPO" "$DIR"
fi

PY="$DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
    uv venv --python 3.12 "$DIR/.venv"
fi

if [[ "$(uname)" == "Darwin" ]]; then
    # macOS torch wheels are CPU/MPS builds already.
    uv pip install --python "$PY" torch torchvision torchaudio
else
    uv pip install --python "$PY" torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu
fi
uv pip install --python "$PY" -r "$DIR/requirements.txt"

echo "ComfyUI $REF ready at $DIR"
echo "COMFYUI_PYTHON=$PY"
