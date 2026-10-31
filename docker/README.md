# OpenJet CUDA Megakernel Engine Container

## Purpose

This repository and container image package and run **only** the CUDA "megakernel" inference engine from OpenJet (`megakernel/`).

The megakernel is an inference engine specialised for **Qwen3.8-27B Q4_K_M GGUF**. It combines persistent cooperative megakernel decoding (each decode step is a single kernel launch), on-device MTP (Multi-Token Prediction) speculative verification, and batched tensor-core prefill. It exposes OpenAI- and Anthropic-compatible HTTP APIs serving:
- `POST /v1/chat/completions` (and `/chat/completions`) — OpenAI Chat Completions (streaming and non-streaming)
- `POST /v1/responses` (and `/responses`) — OpenAI Responses API (Codex CLI)
- `POST /v1/messages` — Anthropic Messages API (Anthropic Claude Code and compatible tools)
- `POST /v1/messages/count_tokens` — Anthropic token count (tokenizer only; computes counts immediately without waiting for an active generation)
- `GET /health` (and `/v1/health`) — readiness check
- `GET /v1/models` (and `/models`) — loaded model ID
- `GET /slots` — slot state inspection when running with `--parallel`

By design, this engine image contains **NO** fallback to `llama-server`. If the GPU hardware or model format does not meet the megakernel's strict requirements, the container halts immediately with an explicit error.

---

## Image Tags

| Tag | Description |
|---|---|
| `latest` | The current stable build using the upstream-pinned `llama.cpp` reference (`LLAMA_CPP_MTP_REF` in `src/provisioning.py`). Updated only after passing all smoke tests. |
| `previous` | The previous stable `latest` image, retained before moving `latest` so you can quickly roll back if needed. |
| `edge` | An experimental build using the newest release tag from `ggml-org/llama.cpp` (checked and bumped at most once weekly), validated against the same smoke tests. `latest` is never moved by an `edge` build. |
| `sha-<openjet7>-<llama ref>-<repo7>` | Immutable versioned tags specifying the 7-character OpenJet commit SHA, the `llama.cpp` reference, and this repository's 7-character commit SHA (e.g. `sha-9b28b81-b10246-0c2da59`). Existing immutable tags are checked before push and never overwritten. |

---

## Supported GPUs and Hardware Requirements

| GPU Architecture | Compute Capability | Target Library | Status | Minimum VRAM |
|---|---|---|---|---|
| **NVIDIA Ampere (RTX 3090, RTX 3080 24GB)** | `8.6` | `libqwen38mk_sm86.so` | **Verified & Tuned** | **24 GB+** (≥23 GB detected) |
| **NVIDIA Ada Lovelace (RTX 4090, RTX 4080)** | `8.9` | `libqwen38mk_sm89.so` | Compiled, Untested | **24 GB+** (≥23 GB detected) |
| **NVIDIA Blackwell (RTX 5090)** | `12.0` | `libqwen38mk_sm120.so` | Compiled, Untested | **24 GB+** (≥23 GB detected) |

### Strict Hardware Constraints:
- **VRAM**: Requires at least **24 GB VRAM** (the startup script verifies that `nvidia-smi` detects at least 23,000 MiB). Any GPU with less than 23 GB VRAM fails immediately at startup.
- **Compute Capability**: Only compute capabilities `8.6`, `8.9`, and `12.0` are accepted. Cards with other architectures (e.g. sm_75 Turing or sm_80 Hopper/A100) are rejected.
- **Concurrency & Slots**: `PARALLEL=1` is the tested default (serving one request at a time). With `PARALLEL > 1` or `AGENTS > 0`, context is per slot or pooled from remaining memory. Available GPU VRAM limits how many slots fit on a 24 GB card.

---

## Environment Variables

| Variable | Description | Default | Allowed Values / Examples |
|---|---|---|---|
| `PUID` | User ID for process execution and file creation | `0` | e.g. `1000` (defaults to root for direct volume writability) |
| `PGID` | Group ID for process execution and file creation | `0` | e.g. `1000` (defaults to root for direct volume writability) |
| `MODEL_REPO` | Hugging Face repository containing the GGUF model | `lmstudio-community/Qwen3.8-27B-GGUF` | e.g. `unsloth/Qwen3.8-27B-GGUF` |
| `MODEL_FILE` | Specific GGUF model file to use | `Qwen3.8-27B-Q4_K_M.gguf` | Must be a Qwen3.8-27B Q4_K_M GGUF |
| `MODEL_DIR` | In-container directory where the model file is stored | `/models` | Absolute directory path |
| `HF_HOME` | Hugging Face download and metadata cache directory | `/models/.cache/huggingface` | Directory path (persists in models volume) |
| `HOST` | Network interface address for the HTTP server to bind | `0.0.0.0` | IP address (e.g. `0.0.0.0`, `127.0.0.1`) |
| `PORT` | TCP port for the HTTP server | `18080` | Port number (integer) |
| `CTX` | Context window size in token positions | `100000` (for `PARALLEL=1`) | Integer (e.g. `32768`, `65536`, `100000`) |
| `DRAFT` | Number of speculative MTP draft tokens per cycle | `4` | Integer (typically `2` to `5`; `0` disables speculation) |
| `KV` | KV cache storage format | `auto` | `auto`, `f16`, `q8` (`auto` selects `q8_0` when fp16 does not fit) |
| `PARALLEL` | Requests decoded together (slots; each holds its own KV cache of `--ctx` positions; 1: one at a time). Tested default is 1. | `1` | Integer (e.g. `1`, `2`, `4`). Mutually exclusive with `AGENTS`. |
| `AGENTS` | Serve N agents at once (`--parallel N` with all memory left as their context, pooled; `-c 0` unless given). | *(unset)* | Integer (e.g. `2`, `4`). Mutually exclusive with `PARALLEL`. |
| `SHARED_CONTEXT` | Path to text file every conversation starts with (in system message), prefilled once at startup and stored once so all agents share that context (used with `--parallel`). | *(unset)* | File path (e.g. `/models/prompt.txt`) |
| `NO_SHARED_PREFIX` | With `--parallel`: don't store shared prompt prefixes once (by default system prompts and tools repeated across conversations are prefilled once and shared). | `0` | `0` (off, shared prefix enabled), `1` (turn off sharing) |
| `UPDATE_MODEL` | Whether to check/download an updated model on startup | `1` | `1` (check on start, continue with existing on failure), `0` (skip check) |
| `HF_TOKEN` | Optional Hugging Face API access token | *(unset)* | Personal access token (`hf_...`) |
| `EXTRA_ARGS` | Additional command-line flags forwarded to `openjet-engine` | *(unset)* | Any additional `openjet-engine` flags |

---

## Volumes

| Container Path | Host Recommended | Purpose | Permissions |
|---|---|---|---|
| `/models` | `./models` (or persistent volume) | Stores the downloaded GGUF model file and the Hugging Face cache (`/models/.cache/huggingface`) so models persist across container updates. | Writable by `PUID:PGID` (default `0:0`). |

---

## How Updates Work

The automated maintenance pipeline keeps this container up to date with upstream changes without manual intervention:

1. **Daily Check (`.github/workflows/check-updates.yml`)**:
   - Runs daily at `03:00 UTC` or via manual dispatch.
   - Resolves the latest upstream commit touching `megakernel/` in `L-Forster/open-jet`.
   - Reads `LLAMA_CPP_MTP_REF` from `src/provisioning.py` at that commit to maintain the pinned, stable build.
   - Resolves the latest release tag from `ggml-org/llama.cpp` for the `edge` build (bumped at most once per 7 days unless OpenJet commit changed).
   - If either changed, updates `docker/versions.json`, commits and pushes to `master`, and invokes `build.yml`.
   - Executes a monthly keepalive commit to ensure GitHub does not disable scheduled actions after 60 days of inactivity.

2. **Build, Test & Promotion Pipeline (`.github/workflows/build.yml`)**:
   - At build time, checks out only `megakernel/` from `L-Forster/open-jet` at the pinned commit.
   - Builds for `linux/amd64` using `docker/build-push-action@v6` with layer caching.
   - Cross-compiles for `sm_86`, `sm_89`, and `sm_120`.
   - Tags the stable image with `sha-<openjet7>-<llama_cpp_ref>-<repo7>`.
   - Runs CPU-only smoke tests:
     - `openjet-engine --help` runs successfully.
     - `ldd` verifies all dynamic dependencies resolve for all three architecture libraries.
     - `libllama.so` loads successfully via Python `ctypes` and `megakernel.server.mk_server` imports cleanly.
   - **Promotion**: After smoke tests pass, retags the existing `latest` image as `previous`, then moves `latest` to the new stable image.
   - **Edge Build**: If an edge ref is present, builds and tests the edge image, tagging as `sha-<openjet7>-<edge>-<repo7>` and promoting to `edge`. The `latest` tag is untouched by edge. Existing immutable tags are checked before push and never overwritten.
   - **Failure Handling**: If any build or smoke test fails, opens or updates a GitHub issue documenting the failure and leaves `latest` untouched.

---

## Troubleshooting

### 1. `ERROR: 'nvidia-smi' command not found`
- **Cause**: The NVIDIA Container Toolkit is not configured on the host or the container was not granted GPU access.
- **Resolution**: Ensure the NVIDIA Container Toolkit is installed and the container definition includes GPU reservations (`capabilities: [gpu]` in Docker Compose).

### 2. `ERROR: Both PARALLEL and AGENTS are set in the environment`
- **Cause**: `PARALLEL` and `AGENTS` were both defined.
- **Resolution**: Use `PARALLEL` for fixed context slots (e.g. `PARALLEL=1`), or `AGENTS` for dynamically pooled context memory. Do not configure both simultaneously.

### 3. `ERROR: Unsupported GPU compute capability`
- **Cause**: The detected GPU is not sm_86 (8.6), sm_89 (8.9), or sm_120 (12.0).
- **Resolution**: The megakernel engine contains tailored assembly and PTX instructions specifically for RTX 30, 40, and 50 series architectures. There is no fallback to CPU or other GPU architectures.

### 4. `ERROR: Insufficient VRAM detected (< 23000 MiB)`
- **Cause**: The GPU has less than 24 GB VRAM (or too much VRAM is allocated to other processes).
- **Resolution**: Qwen3.8-27B Q4_K_M requires approximately 15.5 GB for model weights plus several gigabytes for KV cache and activations. The engine enforces a 24 GB+ VRAM requirement.

### 5. Model Loader Rejection / `RuntimeError` on Startup
- **Cause**: The provided GGUF file is not a valid Qwen3.8-27B Q4_K_M file.
- **Resolution**: The megakernel checks every tensor type at load time. If a different quant format (e.g. Q4_0, Q5_K_M, or unsloth UD-*) or a different model architecture is provided, the loader rejects it and prints the first mismatching tensor. Ensure `MODEL_REPO` and `MODEL_FILE` point to a supported Qwen3.8-27B Q4_K_M GGUF.

### 6. Hugging Face Offline or Rate Limited on Startup
- **Behavior**: If the model file already exists locally in `/models`, the entrypoint attempts to check for updates. If Hugging Face is unreachable or rate limited, it prints a warning and proceeds with the existing model file without failing.

### 7. CUDA Out-of-Memory During Startup Warm-up
- **Cause**: The requested context size (`CTX`) combined with the KV cache mode exceeds available VRAM.
- **Resolution**: Set `KV=q8` or reduce `CTX` (e.g., from `100000` to `65536` or `32768`).

---

## AGPL-3.0 License & Credits

This container distribution is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0).

- **OpenJet**: Specialised CUDA inference engine by L-Forster (OpenJet) and contributors. Upstream repository: https://github.com/L-Forster/open-jet
- **llama.cpp**: Tokenizer and tensor library by the ggml authors (llama.cpp) and contributors (MIT License). Repository: https://github.com/ggml-org/llama.cpp
- **Container Distribution**: Webster Wh (https://github.com/websterwh/openjet-engine-docker)
