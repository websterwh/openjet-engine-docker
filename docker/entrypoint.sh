#!/usr/bin/env bash
set -euo pipefail

# OpenJet CUDA Megakernel Engine Entrypoint
# Requirements:
# - No sleep commands used anywhere
# - PUID/PGID support (defaults to 0:0 for seamless host volume writability)
# - Fast-fail if GPU is unsupported (<23GB VRAM or != sm86, sm89, sm120)
# - No llama-server fallback
# - If model exists and hf update check fails, continue with existing file
# - Expose PARALLEL, AGENTS, SHARED_CONTEXT, NO_SHARED_PREFIX as env vars
# - Refuse to start if PARALLEL and AGENTS are both set

PUID="${PUID:-0}"
PGID="${PGID:-0}"

MODEL_REPO="${MODEL_REPO:-lmstudio-community/Qwen3.8-27B-GGUF}"
MODEL_FILE="${MODEL_FILE:-Qwen3.8-27B-Q4_K_M.gguf}"
MODEL_DIR="${MODEL_DIR:-/models}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-18080}"
INTERNAL_PORT="${INTERNAL_PORT:-18081}"
IDLE_TIMEOUT="${IDLE_TIMEOUT:-0}"
DRAFT="${DRAFT:-4}"
KV="${KV:-auto}"
UPDATE_MODEL="${UPDATE_MODEL:-1}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

if ! [[ "$IDLE_TIMEOUT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: IDLE_TIMEOUT must be a non-negative integer (got '${IDLE_TIMEOUT}')." >&2
    exit 1
fi
export HF_HOME="${HF_HOME:-/models/.cache/huggingface}"

# 1. Parallel and Agent slot configuration
# Normalize whitespace
PARALLEL="$(echo -n "${PARALLEL:-}" | tr -d '[:space:]')"
AGENTS="$(echo -n "${AGENTS:-}" | tr -d '[:space:]')"

# Refuse to start if both PARALLEL and AGENTS are set in environment
if [ -n "${PARALLEL}" ] && [ -n "${AGENTS}" ]; then
    echo "ERROR: Both PARALLEL ('${PARALLEL}') and AGENTS ('${AGENTS}') are set in the environment." >&2
    echo "Refusing to start: choose only one (--parallel for fixed slots or --agents for dynamic pooled slots)." >&2
    exit 1
fi

# Set default: if neither PARALLEL nor AGENTS is set, default to PARALLEL=1
if [ -z "${PARALLEL}" ] && [ -z "${AGENTS}" ]; then
    PARALLEL=1
fi

# Context default: keep CTX=100000 as default when PARALLEL=1
if [ "${PARALLEL}" = "1" ]; then
    CTX="${CTX:-100000}"
else
    CTX="${CTX:-}"
fi

SHARED_CONTEXT="${SHARED_CONTEXT:-}"
NO_SHARED_PREFIX="${NO_SHARED_PREFIX:-0}"

echo "=========================================================="
echo " Starting OpenJet CUDA Megakernel Engine Container"
echo " User ID: ${PUID}, Group ID: ${PGID}"
echo "=========================================================="

# 2. Detect GPU compute capability and VRAM via nvidia-smi
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: 'nvidia-smi' command not found." >&2
    echo "Ensure NVIDIA Container Toolkit is installed on the host and the container" >&2
    echo "is started with GPU access (e.g., deploy.resources.reservations.devices in compose)." >&2
    exit 1
fi

GPU_OUTPUT=$(nvidia-smi --query-gpu=compute_cap,memory.total --format=csv,noheader,nounits 2>&1) || {
    echo "ERROR: Failed to run nvidia-smi:" >&2
    echo "$GPU_OUTPUT" >&2
    exit 1
}

FIRST_GPU_LINE=$(echo "$GPU_OUTPUT" | head -n 1)
if [ -z "$FIRST_GPU_LINE" ]; then
    echo "ERROR: No NVIDIA GPU detected by nvidia-smi." >&2
    exit 1
fi

COMPUTE_CAP=$(echo "$FIRST_GPU_LINE" | cut -d',' -f1 | tr -d '[:space:]')
VRAM_MIB=$(echo "$FIRST_GPU_LINE" | cut -d',' -f2 | tr -d '[:space:]' | cut -d'.' -f1)

echo "Detected primary GPU: Compute Capability ${COMPUTE_CAP}, VRAM ${VRAM_MIB} MiB"

# Map compute capability to target architecture
ARCH=""
case "$COMPUTE_CAP" in
    8.6)
        ARCH="sm86"
        ;;
    8.9)
        ARCH="sm89"
        ;;
    12.0)
        ARCH="sm120"
        ;;
    *)
        echo "ERROR: Unsupported GPU compute capability '${COMPUTE_CAP}'." >&2
        echo "OpenJet megakernel engine supports ONLY sm_86 (RTX 3090), sm_89 (RTX 4090), and sm_120 (RTX 5090)." >&2
        echo "There is NO llama-server fallback in this engine image. Exiting." >&2
        exit 1
        ;;
esac

# Check VRAM (requires at least 23 GB VRAM; 24 GB cards report ~24576 MiB)
if [ "$VRAM_MIB" -lt 23000 ]; then
    echo "ERROR: Insufficient VRAM detected (${VRAM_MIB} MiB)." >&2
    echo "The OpenJet megakernel engine requires 24 GB+ VRAM (minimum 23 GB detected)." >&2
    echo "There is NO llama-server fallback in this engine image. Exiting." >&2
    exit 1
fi

# 3. Select matching precompiled megakernel library
LIB_PATH="${LIB_PATH:-/opt/open-jet/libs/libqwen38mk_${ARCH}.so}"
if [ ! -f "$LIB_PATH" ]; then
    echo "ERROR: Megakernel library for ${ARCH} not found at '${LIB_PATH}'." >&2
    exit 1
fi
echo "Selected engine library: ${LIB_PATH} (target: ${ARCH})"

# 4. Model directory preparation and permissions
mkdir -p "$MODEL_DIR" "$HF_HOME"

if [ "$(id -u)" -eq 0 ] && { [ "$PUID" -ne 0 ] || [ "$PGID" -ne 0 ]; }; then
    for grp in video render; do
        if ! getent group "$grp" >/dev/null 2>&1; then
            groupadd -r "$grp" 2>/dev/null || true
        fi
    done
    groupadd -g "$PGID" -o openjet 2>/dev/null || true
    EXISTING_GROUPS=""
    for grp in video render; do
        if getent group "$grp" >/dev/null 2>&1; then
            EXISTING_GROUPS="${EXISTING_GROUPS:+$EXISTING_GROUPS,}$grp"
        fi
    done
    USERADD_ARGS=(-u "$PUID" -g "$PGID" -o -d /home/openjet -m -s /bin/bash)
    if [ -n "$EXISTING_GROUPS" ]; then
        USERADD_ARGS+=(-G "$EXISTING_GROUPS")
    fi
    useradd "${USERADD_ARGS[@]}" openjet 2>/dev/null || true
    mkdir -p /home/openjet
    chown -R "${PUID}:${PGID}" "$MODEL_DIR" /home/openjet 2>/dev/null || true
fi

TARGET_MODEL="${MODEL_DIR}/${MODEL_FILE}"

if [ ! -f "$TARGET_MODEL" ]; then
    echo "Model file '$TARGET_MODEL' not found. Downloading from '$MODEL_REPO' ($MODEL_FILE)..."
    HF_ARGS=("$MODEL_REPO" "$MODEL_FILE" --local-dir "$MODEL_DIR")
    if [ -n "${HF_TOKEN:-}" ]; then
        HF_ARGS+=(--token "$HF_TOKEN")
    fi
    hf download "${HF_ARGS[@]}"
elif [ "$UPDATE_MODEL" = "1" ]; then
    echo "Model file exists at '$TARGET_MODEL'. Checking for updates from '$MODEL_REPO'..."
    HF_ARGS=("$MODEL_REPO" "$MODEL_FILE" --local-dir "$MODEL_DIR")
    if [ -n "${HF_TOKEN:-}" ]; then
        HF_ARGS+=(--token "$HF_TOKEN")
    fi
    if ! hf download "${HF_ARGS[@]}"; then
        echo "WARNING: Hugging Face update check failed. Continuing with existing model file '$TARGET_MODEL'." >&2
    fi
fi

if [ ! -f "$TARGET_MODEL" ]; then
    echo "ERROR: Target model file not found at '${TARGET_MODEL}'." >&2
    exit 1
fi

DRAFT_VOCAB="${DRAFT_VOCAB:-/opt/open-jet/megakernel/draft_vocab_32k.bin}"
if [ ! -f "$DRAFT_VOCAB" ]; then
    echo "ERROR: Draft vocabulary file not found at '${DRAFT_VOCAB}'." >&2
    exit 1
fi

echo "=========================================================="
echo " Starting openjet-engine with configuration:"
echo " Model:          ${TARGET_MODEL}"
echo " Host:           ${HOST}"
echo " Port:           ${PORT}"
if [ "$IDLE_TIMEOUT" -gt 0 ]; then
    echo " Idle Timeout:   ${IDLE_TIMEOUT} min (internal port: ${INTERNAL_PORT})"
fi
if [ -n "${CTX}" ]; then
    echo " Context:        ${CTX}"
fi
echo " Draft:          ${DRAFT}"
echo " KV Mode:        ${KV}"
echo " Library:        ${LIB_PATH}"
echo " Draft Vocab:    ${DRAFT_VOCAB}"
if [ -n "${PARALLEL}" ]; then
    echo " Parallel Slots: ${PARALLEL}"
fi
if [ -n "${AGENTS}" ]; then
    echo " Agents (pool):  ${AGENTS}"
fi
if [ -n "${SHARED_CONTEXT}" ]; then
    echo " Shared Context: ${SHARED_CONTEXT}"
fi
if [ "${NO_SHARED_PREFIX:-0}" = "1" ] || [ "${NO_SHARED_PREFIX:-false}" = "true" ] || [ "${NO_SHARED_PREFIX:-off}" = "on" ]; then
    echo " Shared Prefix:  Disabled (--no-shared-prefix)"
fi
if [ -n "${EXTRA_ARGS}" ]; then
    echo " Extra Args:     ${EXTRA_ARGS}"
fi
echo "=========================================================="

# 5. Build openjet-engine command
# Pass flags to openjet-engine ONLY when set
ENGINE_HOST="$HOST"
ENGINE_PORT="$PORT"
if [ "$IDLE_TIMEOUT" -gt 0 ]; then
    ENGINE_HOST="127.0.0.1"
    ENGINE_PORT="$INTERNAL_PORT"
fi

CMD=(
    openjet-engine
    -m "$TARGET_MODEL"
    --host "$ENGINE_HOST"
    --port "$ENGINE_PORT"
    -d "$DRAFT"
    --draft-vocab "$DRAFT_VOCAB"
    --lib "$LIB_PATH"
    --kv "$KV"
)

if [ -n "${CTX}" ]; then
    CMD+=(-c "$CTX")
fi

if [ -n "${PARALLEL}" ]; then
    CMD+=(--parallel "$PARALLEL")
fi

if [ -n "${AGENTS}" ]; then
    CMD+=(--agents "$AGENTS")
fi

if [ -n "${SHARED_CONTEXT}" ]; then
    CMD+=(--shared-context "$SHARED_CONTEXT")
fi

if [ "${NO_SHARED_PREFIX:-0}" = "1" ] || [ "${NO_SHARED_PREFIX:-false}" = "true" ] || [ "${NO_SHARED_PREFIX:-off}" = "on" ]; then
    CMD+=(--no-shared-prefix)
fi

if [ -n "${EXTRA_ARGS}" ]; then
    # shellcheck disable=SC2086,SC2206
    CMD+=($EXTRA_ARGS)
fi

if [ "$IDLE_TIMEOUT" -gt 0 ]; then
    PROXY_BIN="/usr/local/bin/idle_proxy.py"
    if [ ! -f "$PROXY_BIN" ]; then
        PROXY_BIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/idle_proxy.py"
    fi
    set -- python3 "$PROXY_BIN" --host "$HOST" --port "$PORT" --internal-port "$INTERNAL_PORT" --idle-timeout "$IDLE_TIMEOUT" -- "${CMD[@]}"
else
    set -- "${CMD[@]}"
fi

if [ "$(id -u)" -eq 0 ] && { [ "$PUID" -ne 0 ] || [ "$PGID" -ne 0 ]; }; then
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$@"
else
    exec "$@"
fi
