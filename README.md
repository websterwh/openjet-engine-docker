# openjet-engine-docker

Standalone Docker packaging and automated GitHub Actions CI/CD for the **OpenJet CUDA Megakernel Inference Engine** specialised for **Qwen3.8-27B Q4_K_M GGUF**.

Upstream project: [L-Forster/open-jet](https://github.com/L-Forster/open-jet)  
Container image: `ghcr.io/websterwh/openjet-engine:latest`

---

## Overview

This repository isolates and automates container builds for the high-performance CUDA megakernel inference engine from OpenJet. It runs purely the CUDA engine without the OpenJet desktop, agent, or TUI components.

- **Target Model:** Qwen3.8-27B Q4_K_M GGUF (strictly verified by the engine loader).
- **Supported GPUs:** sm_86 (RTX 3090 / 3080 24GB, verified & tuned), sm_89 (RTX 4090 / 4080), and sm_120 (RTX 5090).
- **VRAM Requirement:** 24 GB+ VRAM (minimum 23 GB detected).
- **No CPU / llama-server Fallback:** Fails fast with clear diagnostics if hardware or quant requirements are not met.
- **API Endpoints:**
  - `POST /v1/chat/completions` (OpenAI Chat Completions)
  - `POST /v1/responses` (OpenAI Responses / Codex CLI)
  - `POST /v1/messages` (Anthropic Messages API / Claude Code)
  - `POST /v1/messages/count_tokens` (Anthropic token count, tokenizer only)
  - `GET /health` (Readiness check)
  - `GET /v1/models` (Model ID)
  - `GET /slots` (Slot state inspection with `--parallel`)

---

## Image Tags

| Tag | Description |
|---|---|
| `latest` | The current stable build using the upstream-pinned `llama.cpp` reference (`LLAMA_CPP_MTP_REF` in `src/provisioning.py`). Updated only after passing all smoke tests. |
| `previous` | The previous stable `latest` image, retained before moving `latest` so you can quickly roll back if needed. |
| `edge` | An experimental build using the newest release tag from `ggml-org/llama.cpp` (checked and bumped at most once weekly), validated against the same smoke tests. `latest` is never moved by an `edge` build. |
| `sha-<openjet7>-<llama ref>-<repo7>` | Immutable versioned tags specifying the 7-character OpenJet commit SHA, the `llama.cpp` reference, and this repository's 7-character commit SHA (e.g. `sha-9b28b81-b10246-0c2da59`). Existing immutable tags are checked before push and never overwritten. |

---

## Quick Configuration (Docker Compose)

See [`docker-compose.example.yml`](docker-compose.example.yml):

```yaml
services:
  openjet:
    image: ghcr.io/websterwh/openjet-engine:latest
    container_name: openjet-megakernel
    restart: unless-stopped
    ports:
      - "18080:18080"
    environment:
      - PUID=0
      - PGID=0
      - MODEL_REPO=lmstudio-community/Qwen3.8-27B-GGUF
      - MODEL_FILE=Qwen3.8-27B-Q4_K_M.gguf
      - MODEL_DIR=/models
      - HOST=0.0.0.0
      - PORT=18080
      - CTX=100000
      - DRAFT=4
      - KV=auto
      - PARALLEL=1
      # - AGENTS=4
      # - SHARED_CONTEXT=/models/shared_system_prompt.txt
      # - NO_SHARED_PREFIX=0
      - UPDATE_MODEL=1
    volumes:
      - ./models:/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

### Note on Concurrency and Slots
With `PARALLEL > 1`, requests are decoded together in slots where each slot holds its own KV cache of `--ctx` positions (`PARALLEL=1` is the tested default). When using `AGENTS=N`, all remaining memory is pooled across N agent slots (`-c 0`). Total GPU VRAM limits how many slots fit on a 24 GB card.

---

## Detailed Documentation

For environment variables, volume mappings, update mechanisms, hardware details, and troubleshooting, see **[`docker/README.md`](docker/README.md)**.

---

## AGPL-3.0 Compliance & Credits

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See **[`SOURCE.md`](SOURCE.md)** and **[`LICENSE`](LICENSE)**.

- **OpenJet**: Specialised CUDA inference engine by L-Forster (OpenJet) and contributors. (AGPL-3.0)
- **llama.cpp**: Tokenizer and tensor library by the ggml authors (llama.cpp) and contributors. (MIT)
- **Container Distribution**: Webster Wh (https://github.com/websterwh/openjet-engine-docker)
