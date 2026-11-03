# syntax=docker/dockerfile:1

# ==============================================================================
# Stage 1: Build stage (CUDA 12.9 Devel on Ubuntu 24.04)
# ==============================================================================
FROM nvidia/cuda:12.9.2-devel-ubuntu24.04 AS builder

ARG OPENJET_COMMIT=ad5e66ef1235d665a8e7fb55bca6fddee295aa9c
ARG LLAMA_CPP_REF=b10246

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    make \
    g++ \
    ca-certificates \
    python3 \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Strict check: NVCC must exist and be executable at absolute path /usr/local/cuda/bin/nvcc
RUN if [ ! -x /usr/local/cuda/bin/nvcc ]; then \
        echo "ERROR: /usr/local/cuda/bin/nvcc not found or not executable" >&2; \
        exit 1; \
    fi

WORKDIR /opt/open-jet

# 1. Clone llama.cpp at pinned ref and compile CPU-only tokenizer shared libraries
RUN git clone --depth 1 --branch "${LLAMA_CPP_REF}" https://github.com/ggml-org/llama.cpp.git /opt/open-jet/llama.cpp

WORKDIR /opt/open-jet/llama.cpp
RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DGGML_CUDA=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_OPENMP=OFF \
    -DLLAMA_OPENSSL=OFF \
    -DLLAMA_BUILD_COMMON=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_TOOLS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_SERVER=OFF \
    -DLLAMA_BUILD_APP=OFF \
    -DLLAMA_BUILD_UI=OFF \
    && cmake --build build -j"$(nproc)" --target llama ggml-base

# 2. Copy megakernel source from build context
COPY megakernel /opt/open-jet/megakernel

# 3. Cross-compile libqwen38mk.so for sm_86, sm_89, and sm_120
# Always pass NVCC as an absolute path and clean between architecture builds.
WORKDIR /opt/open-jet/megakernel
RUN mkdir -p /opt/open-jet/libs \
    # sm_86 (RTX 3090, RTX 3080 24GB)
    && make clean \
    && make -j1 NVCC=/usr/local/cuda/bin/nvcc ARCH=sm_86 LLAMA=/opt/open-jet/llama.cpp RPATH=/opt/open-jet/llama.cpp/build/bin libqwen38mk.so \
    && cp libqwen38mk.so /opt/open-jet/libs/libqwen38mk_sm86.so \
    # sm_89 (RTX 4090, RTX 4080)
    && make clean \
    && make -j1 NVCC=/usr/local/cuda/bin/nvcc ARCH=sm_89 LLAMA=/opt/open-jet/llama.cpp RPATH=/opt/open-jet/llama.cpp/build/bin libqwen38mk.so \
    && cp libqwen38mk.so /opt/open-jet/libs/libqwen38mk_sm89.so \
    # sm_120 (RTX 5090)
    && make clean \
    && make -j1 NVCC=/usr/local/cuda/bin/nvcc ARCH=sm_120 LLAMA=/opt/open-jet/llama.cpp RPATH=/opt/open-jet/llama.cpp/build/bin libqwen38mk.so \
    && cp libqwen38mk.so /opt/open-jet/libs/libqwen38mk_sm120.so \
    && make clean

# ==============================================================================
# Stage 2: Runtime stage (CUDA 12.9 Runtime on Ubuntu 24.04)
# ==============================================================================
FROM nvidia/cuda:12.9.2-runtime-ubuntu24.04

ARG OPENJET_COMMIT=ad5e66ef1235d665a8e7fb55bca6fddee295aa9c
ARG LLAMA_CPP_REF=b10246

# OCI labels according to AGPL source offer and project metadata
LABEL org.opencontainers.image.source="https://github.com/websterwh/openjet-engine-docker" \
      org.opencontainers.image.licenses="AGPL-3.0" \
      org.opencontainers.image.title="OpenJet CUDA Megakernel Engine" \
      org.opencontainers.image.description="Standalone container for OpenJet CUDA megakernel inference engine (Qwen3.8-27B Q4_K_M)" \
      ai.openjet.upstream.repo="https://github.com/L-Forster/open-jet" \
      ai.openjet.upstream.sha="${OPENJET_COMMIT}" \
      ai.openjet.megakernel.llama_cpp_ref="${LLAMA_CPP_REF}"

ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies (including util-linux for setpriv)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    curl \
    ca-certificates \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Set up isolated Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install required pip packages
RUN pip install --no-cache-dir jinja2 huggingface_hub

WORKDIR /opt/open-jet

# Copy CPU-only llama.cpp libraries into the exact RPATH location (/opt/open-jet/llama.cpp/build/bin)
RUN mkdir -p /opt/open-jet/llama.cpp/build/bin
COPY --from=builder /opt/open-jet/llama.cpp/build/bin/lib*.so* /opt/open-jet/llama.cpp/build/bin/

# Copy compiled architecture-specific megakernel libraries
RUN mkdir -p /opt/open-jet/libs
COPY --from=builder /opt/open-jet/libs/ /opt/open-jet/libs/

# Copy megakernel package (includes server/mk_server.py and draft_vocab_32k.bin)
COPY megakernel /opt/open-jet/megakernel

# Install megakernel package in editable mode to register the openjet-engine CLI
RUN pip install --no-cache-dir -e /opt/open-jet/megakernel

# Copy licenses into /licenses per AGPL requirements
RUN mkdir -p /licenses
COPY LICENSE /licenses/LICENSE.openjet
COPY SOURCE.md /licenses/SOURCE.md
COPY --from=builder /opt/open-jet/llama.cpp/LICENSE /licenses/LICENSE.llama.cpp

# Copy entrypoint and idle proxy scripts
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/idle_proxy.py /usr/local/bin/idle_proxy.py
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/idle_proxy.py
# Prepare models directory and grant read permissions to libs
RUN mkdir -p /models \
    && chmod -R a+rX /opt/open-jet /opt/venv /licenses

# Runtime configuration environment variables
ENV MODEL_REPO=lmstudio-community/Qwen3.8-27B-GGUF \
    MODEL_FILE=Qwen3.8-27B-Q4_K_M.gguf \
    MODEL_DIR=/models \
    HOST=0.0.0.0 \
    PORT=18080 \
    IDLE_TIMEOUT=0 \
    CTX=100000 \
    DRAFT=4 \
    KV=auto \
    UPDATE_MODEL=1 \
    PUID=0 \
    PGID=0 \
    HF_HOME=/models/.cache/huggingface \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    LD_LIBRARY_PATH="/opt/open-jet/llama.cpp/build/bin:/opt/open-jet/libs:${LD_LIBRARY_PATH:-}"

EXPOSE 18080

HEALTHCHECK --interval=10s --timeout=5s --start-period=15m --retries=3 \
  CMD curl -f "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
