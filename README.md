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
- **API Endpoints:** OpenAI-compatible (`/v1/chat/completions`, `/v1/models`), Anthropic-compatible (`/v1/messages`), and `/health`.

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

---

## Detailed Documentation

For environment variables, volume mappings, update mechanisms, hardware details, and troubleshooting, see **[`docker/README.md`](docker/README.md)**.

---

## AGPL-3.0 Compliance & Credits

This project is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). See **[`SOURCE.md`](SOURCE.md)** and **[`LICENSE`](LICENSE)**.

- **OpenJet**: Specialised CUDA inference engine by L-Forster (OpenJet) and contributors. (AGPL-3.0)
- **llama.cpp**: Tokenizer and tensor library by the ggml authors (llama.cpp) and contributors. (MIT)
- **Container Distribution**: Webster Wh (https://github.com/websterwh/openjet-engine-docker)
