#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Running Python idle-proxy integration test suite ==="
python3 "${DIR}/tests/test_idle_proxy.py"

echo "=== Testing IDLE_TIMEOUT input validation ==="

# Test negative number
set +e
OUT_NEG=$(python3 "${DIR}/idle_proxy.py" --idle-timeout -1 -- /bin/true 2>&1)
CODE_NEG=$?
set -e
if [ "$CODE_NEG" -ne 1 ]; then
    echo "ERROR: Expected exit 1 for negative IDLE_TIMEOUT, got $CODE_NEG" >&2
    exit 1
fi
echo "$OUT_NEG" | grep -F "ERROR: IDLE_TIMEOUT must be a non-negative integer"
echo "Negative IDLE_TIMEOUT validation passed."

# Test non-integer string
set +e
OUT_STR=$(python3 "${DIR}/idle_proxy.py" --idle-timeout abc -- /bin/true 2>&1)
CODE_STR=$?
set -e
if [ "$CODE_STR" -ne 1 ]; then
    echo "ERROR: Expected exit 1 for non-integer IDLE_TIMEOUT, got $CODE_STR" >&2
    exit 1
fi
echo "$OUT_STR" | grep -F "ERROR: IDLE_TIMEOUT must be a non-negative integer"
echo "Non-integer IDLE_TIMEOUT validation passed."

# Test missing command
set +e
OUT_NOCMD=$(python3 "${DIR}/idle_proxy.py" --idle-timeout 5 2>&1)
CODE_NOCMD=$?
set -e
if [ "$CODE_NOCMD" -ne 1 ]; then
    echo "ERROR: Expected exit 1 for missing engine command, got $CODE_NOCMD" >&2
    exit 1
fi
echo "$OUT_NOCMD" | grep -F "ERROR: No engine command specified"
echo "Missing command validation passed."

echo "=== Testing entrypoint.sh IDLE_TIMEOUT behavior ==="

# Setup mock environment for entrypoint
MOCK_DIR=$(mktemp -d)
mkdir -p "$MOCK_DIR/stubs" "$MOCK_DIR/models" "$MOCK_DIR/opt/open-jet/libs" "$MOCK_DIR/opt/open-jet/megakernel"
cat << "EOF" > "$MOCK_DIR/stubs/nvidia-smi"
#!/bin/sh
echo "8.6, 24576"
EOF
chmod +x "$MOCK_DIR/stubs/nvidia-smi"

cat << "EOF" > "$MOCK_DIR/stubs/openjet-engine"
#!/bin/sh
echo "MOCK_ENGINE: args: $*"
EOF
chmod +x "$MOCK_DIR/stubs/openjet-engine"

touch "$MOCK_DIR/models/model.gguf"
touch "$MOCK_DIR/opt/open-jet/libs/libqwen38mk_sm86.so"
touch "$MOCK_DIR/opt/open-jet/megakernel/draft_vocab_32k.bin"

MOCK_PATH="$MOCK_DIR/stubs:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MOCK_ENV=(
    PATH="$MOCK_PATH"
    MODEL_DIR="$MOCK_DIR/models"
    MODEL_FILE="model.gguf"
    UPDATE_MODEL="0"
    HF_HOME="$MOCK_DIR/hf_cache"
    LIB_PATH="$MOCK_DIR/opt/open-jet/libs/libqwen38mk_sm86.so"
    DRAFT_VOCAB="$MOCK_DIR/opt/open-jet/megakernel/draft_vocab_32k.bin"
)

# Test (h): IDLE_TIMEOUT=0 leaves old exec path unchanged
echo "Testing IDLE_TIMEOUT=0 direct execution..."
OUT_IDLE_0=$(env -i "${MOCK_ENV[@]}" IDLE_TIMEOUT=0 "${DIR}/entrypoint.sh")
echo "$OUT_IDLE_0" | grep -F "MOCK_ENGINE: args:"
echo "$OUT_IDLE_0" | grep -F -- "--host 0.0.0.0 --port 18080"
if echo "$OUT_IDLE_0" | grep -F "idle_proxy.py"; then
    echo "ERROR: idle_proxy.py should not be invoked when IDLE_TIMEOUT=0" >&2
    exit 1
fi
echo "IDLE_TIMEOUT=0 verified: invokes openjet-engine directly with public host/port."

# Test entrypoint with invalid IDLE_TIMEOUT
set +e
OUT_EP_INV=$(env -i "${MOCK_ENV[@]}" IDLE_TIMEOUT=-2 "${DIR}/entrypoint.sh" 2>&1)
CODE_EP_INV=$?
set -e
if [ "$CODE_EP_INV" -ne 1 ]; then
    echo "ERROR: Expected exit 1 for invalid IDLE_TIMEOUT in entrypoint, got $CODE_EP_INV" >&2
    exit 1
fi
echo "$OUT_EP_INV" | grep -F "ERROR: IDLE_TIMEOUT must be a non-negative integer"
echo "entrypoint IDLE_TIMEOUT validation verified."

rm -rf "$MOCK_DIR"

echo "ALL IDLE PROXY TESTS PASSED CLEANLY!"
