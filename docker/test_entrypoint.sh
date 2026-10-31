#!/usr/bin/env bash
set -euo pipefail

# Setup stub binaries and dummy model directory
mkdir -p /tmp/stubs /tmp/test_models /opt/open-jet/libs /opt/open-jet/megakernel
touch /opt/open-jet/libs/libqwen38mk_sm86.so
touch /opt/open-jet/megakernel/draft_vocab_32k.bin

cat << "EOF" > /tmp/stubs/nvidia-smi
#!/bin/sh
echo "8.6, 24576"
EOF
chmod +x /tmp/stubs/nvidia-smi

cat << "EOF" > /tmp/stubs/openjet-engine
#!/bin/sh
echo "STUB_OUTPUT: uid=$(id -u) gid=$(id -g) args: $*"
EOF
chmod +x /tmp/stubs/openjet-engine

touch /tmp/test_models/test_model.gguf

SYS_PATH="/tmp/stubs:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export MODEL_DIR="/tmp/test_models"
export MODEL_FILE="test_model.gguf"
export UPDATE_MODEL="0"

ENTRYPOINT_BIN="/usr/local/bin/entrypoint.sh"
if [ ! -f "$ENTRYPOINT_BIN" ]; then
    ENTRYPOINT_BIN="/entrypoint.sh"
fi
if [ ! -f "$ENTRYPOINT_BIN" ]; then
    echo "ERROR: Entrypoint script not found at /usr/local/bin/entrypoint.sh or /entrypoint.sh." >&2
    exit 1
fi
echo "Using entrypoint binary: $ENTRYPOINT_BIN"

echo "=== Case 1: Defaults ==="
OUT1=$(env -i PATH="$SYS_PATH" MODEL_DIR="$MODEL_DIR" MODEL_FILE="$MODEL_FILE" UPDATE_MODEL="$UPDATE_MODEL" "$ENTRYPOINT_BIN")
echo "$OUT1" | grep -F "STUB_OUTPUT:"
echo "$OUT1" | grep -F -- "--parallel 1"
echo "$OUT1" | grep -F -- "-c 100000"
if echo "$OUT1" | grep -F -- "--agents"; then
    echo "ERROR: --agents should not be present in Case 1" >&2
    exit 1
fi
echo "Case 1 PASSED"

echo "=== Case 2: AGENTS=2 only ==="
OUT2=$(env -i PATH="$SYS_PATH" MODEL_DIR="$MODEL_DIR" MODEL_FILE="$MODEL_FILE" UPDATE_MODEL="$UPDATE_MODEL" AGENTS=2 "$ENTRYPOINT_BIN")
echo "$OUT2" | grep -F "STUB_OUTPUT:"
echo "$OUT2" | grep -F -- "--agents 2"
if echo "$OUT2" | grep -F -- "--parallel"; then
    echo "ERROR: --parallel should not be present in Case 2" >&2
    exit 1
fi
if echo "$OUT2" | grep -F -- "-c "; then
    echo "ERROR: -c should not be present in Case 2" >&2
    exit 1
fi
echo "Case 2 PASSED"

echo "=== Case 3: PARALLEL=2 with CTX unset ==="
OUT3=$(env -i PATH="$SYS_PATH" MODEL_DIR="$MODEL_DIR" MODEL_FILE="$MODEL_FILE" UPDATE_MODEL="$UPDATE_MODEL" PARALLEL=2 "$ENTRYPOINT_BIN")
echo "$OUT3" | grep -F "STUB_OUTPUT:"
echo "$OUT3" | grep -F -- "--parallel 2"
if echo "$OUT3" | grep -F -- "--agents"; then
    echo "ERROR: --agents should not be present in Case 3" >&2
    exit 1
fi
if echo "$OUT3" | grep -F -- "-c "; then
    echo "ERROR: -c should not be present in Case 3" >&2
    exit 1
fi
echo "Case 3 PASSED"

echo "=== Case 4: Both PARALLEL and AGENTS set (must exit 1) ==="
set +e
OUT4=$(env -i PATH="$SYS_PATH" MODEL_DIR="$MODEL_DIR" MODEL_FILE="$MODEL_FILE" UPDATE_MODEL="$UPDATE_MODEL" PARALLEL=2 AGENTS=2 "$ENTRYPOINT_BIN" 2>&1)
STATUS4=$?
set -e
if [ "$STATUS4" -ne 1 ]; then
    echo "ERROR: Expected exit code 1, got $STATUS4" >&2
    exit 1
fi
echo "$OUT4" | grep -F "Both PARALLEL"
echo "Case 4 PASSED (exited with code 1)"

echo "=== Case 5: PUID=500 and PGID=500 ==="
OUT5=$(env -i PATH="$SYS_PATH" MODEL_DIR="$MODEL_DIR" MODEL_FILE="$MODEL_FILE" UPDATE_MODEL="$UPDATE_MODEL" PUID=500 PGID=500 "$ENTRYPOINT_BIN")
echo "$OUT5" | grep -F "STUB_OUTPUT: uid=500 gid=500"
echo "Case 5 PASSED"

echo "ALL 5 ENTRYPOINT TEST CASES PASSED CLEANLY!"
