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

echo "ALL IDLE PROXY TESTS PASSED CLEANLY!"
