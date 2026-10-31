# Source Code and Licensing Notice (GNU AGPL-3.0)

## Container Image Source Offer

The container images distributed under `ghcr.io/websterwh/openjet-engine` are built from this repository:
- **Repository URL:** https://github.com/websterwh/openjet-engine-docker
- **Upstream Repository:** https://github.com/L-Forster/open-jet
- **Upstream Commit Used:** [ad5e66ef1235d665a8e7fb55bca6fddee295aa9c](https://github.com/L-Forster/open-jet/tree/ad5e66ef1235d665a8e7fb55bca6fddee295aa9c)
- **llama.cpp Reference:** The pinned tokenizer reference used for the stable/`latest` image is `LLAMA_CPP_MTP_REF` from upstream's `src/provisioning.py` (`b10246`), recorded in the image label `ai.openjet.megakernel.llama_cpp_ref`. The experimental `edge` image tracks the latest `ggml-org/llama.cpp` release tag.

The exact source references are recorded as OCI image metadata labels:
- `org.opencontainers.image.source`: `https://github.com/websterwh/openjet-engine-docker`
- `ai.openjet.upstream.repo`: `https://github.com/L-Forster/open-jet`
- `ai.openjet.upstream.sha`: `ad5e66ef1235d665a8e7fb55bca6fddee295aa9c` (or the specific commit built)
- `ai.openjet.megakernel.llama_cpp_ref`: `b10246` (pinned) or edge tag

## Prominent Notice of Modifications

In accordance with Section 5(a) of the GNU Affero General Public License (AGPL-3.0), this notice states that this work is a modified packaging and distribution of the OpenJet inference engine:
- **Upstream Project:** OpenJet (https://github.com/L-Forster/open-jet)
- **Upstream License:** GNU Affero General Public License v3.0 (AGPL-3.0)
- **Original Author Attribution:** L-Forster (OpenJet) and contributors

### Modifications in this Repository:
1. **Repository Scope & Decoupling:**
   - Isolated only the CUDA megakernel inference engine from upstream OpenJet.
   - Removed all agent, TUI, and desktop components. At build time, GitHub Actions checks out only the `megakernel/` directory from upstream `L-Forster/open-jet` at the pinned commit recorded in `docker/versions.json`.
2. **Container Packaging (`docker/Dockerfile`):**
   - Multi-stage Docker build targeting `nvidia/cuda:12.9.2-devel-ubuntu24.04` and `nvidia/cuda:12.9.2-runtime-ubuntu24.04` for `linux/amd64`.
   - Compiles a CPU-only tokenizer build of `llama.cpp` at the pinned reference for `latest` and at the edge release for `edge`.
   - Compiles architecture-specific shared libraries (`libqwen38mk_sm86.so`, `libqwen38mk_sm89.so`, `libqwen38mk_sm120.so`) preserving dynamic linking and RPATH to `/opt/open-jet/llama.cpp/build/bin`.
   - Bundles all license texts inside `/licenses` in the image (`/licenses/LICENSE.openjet`, `/licenses/SOURCE.md`, `/licenses/LICENSE.llama.cpp`).
3. **Container Orchestration & Automation (`docker/entrypoint.sh`, `docker-compose.example.yml`):**
   - Runtime GPU detection via `nvidia-smi` to select the matching architecture library.
   - Hardware enforcement: fast-fails with an informative error if GPU architecture is not sm_86, sm_89, or sm_120, or if total VRAM is less than 23 GB. No fallback to llama-server.
   - PUID/PGID support (defaults to 0:0 for immediate write access to host-mounted volumes, with support for privilege dropping via `setpriv`).
   - Resilient model management via `huggingface_hub`: checks for updates on startup, but continues running with the existing model file if Hugging Face is unreachable.
4. **CI & Automated Upstream Tracking (`.github/workflows/`):**
   - `.github/workflows/check-updates.yml`: automated daily tracking of upstream commits touching `megakernel/` and `llama.cpp` releases. Reads `LLAMA_CPP_MTP_REF` from upstream's `src/provisioning.py` for the pinned build, and tracks edge releases bumped at most weekly. Includes a monthly keepalive commit.
   - `.github/workflows/build.yml`: CI workflow for building `linux/amd64`, layer caching, running CPU smoke tests (library linking, ctypes loading, module import, CLI execution), versioned tagging (`sha-<commit7>-<llama tag>`), retagging `latest` as `previous`, and building the separate `edge` tag.

## Third-Party Components & Credits

- **OpenJet**: Specialised CUDA inference engine by L-Forster (OpenJet) and contributors. Licensed under GNU AGPL-3.0.
- **llama.cpp**: Tokenizer and tensor library by the ggml authors (llama.cpp) and contributors. Licensed under MIT License.
