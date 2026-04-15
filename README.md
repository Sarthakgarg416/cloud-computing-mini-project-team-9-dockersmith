# 🔧 Docksmith

> A simplified Docker-like build and runtime system built from scratch — no daemon, no external runtimes, pure OS primitives.

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat&logo=python&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?style=flat&logo=linux&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

---

## What is Docksmith?

Docksmith reimplements the core of Docker from first principles. It reads a `Docksmithfile`, builds images as stacks of content-addressed tar layers, caches build steps deterministically, and runs containers using Linux namespace isolation — all in a single CLI binary with no daemon.

**Three things built from scratch:**
- A **build system** that parses and executes 6 instructions, producing immutable delta layers stored by SHA-256 digest
- A **deterministic build cache** with hash-chain invalidation so identical builds are near-instant
- A **container runtime** using `unshare` + `chroot` for real process isolation — the same primitive used for both `RUN` during build and `docksmith run`

---

## Team

| Name | Domain | Files |
|------|--------|-------|
| **Garg** | Build Engine + CLI | `engine.py`, `cli.py`, `docksmith.py` |
| **Sneh** | Process Isolation + Runtime + GUI | `isolate.py`, `container.py`, `gui/` |
| **Shravan** | Layers + Image Manifest | `layers.py`, `manifest.py` |
| **Wadhwa** | Build Cache + Image Store + Parser | `cache.py`, `image_store.py`, `parser.py`, `docksmith-import.py` |

---

## Features

- **6 Docksmithfile instructions** — `FROM`, `COPY`, `RUN`, `WORKDIR`, `ENV`, `CMD`
- **Content-addressed layers** — delta tars named by SHA-256 digest, stored in `~/.docksmith/layers/`
- **Deterministic cache** — hash chain over previous digest + instruction + WORKDIR + ENV + file hashes
- **Real container isolation** — Linux `unshare` + `chroot`, verified pass/fail: files written inside never appear on host
- **Fully offline** — base images imported once at setup; zero network access during build or run
- **Reproducible builds** — sorted tar entries, zeroed timestamps, canonical JSON digest

---

## Requirements

- Linux (Ubuntu 20.04+ recommended)
- Python 3.8+
- Root or `sudo` access (required for `unshare` namespace isolation)
- `util-linux` package (`unshare` binary)

> **macOS / Windows:** Use a Linux VM (WSL2, VirtualBox, etc.)

---

## Installation

```bash
# Clone the repo
git clone https://github.com/yourteam/docksmith.git
cd docksmith

# Install Python dependencies
pip install -r requirements.txt

# Import base images (one-time setup — requires internet)
sudo python docksmith-import.py
# or
sudo python setup-images.py
```

After this, **everything works fully offline**.

---

## State Directory

All state lives in `~/.docksmith/`:

```
~/.docksmith/
├── images/          # JSON manifest per image
│   └── myapp_latest.json
├── layers/          # Content-addressed tar files, named by SHA-256 digest
│   ├── sha256:aaa....tar
│   └── sha256:bbb....tar
└── cache/           # Index mapping cache keys → layer digests
    └── index.json
```

---

## Docksmithfile Reference

```dockerfile
FROM alpine:3.18          # Load base image layers from local store
WORKDIR /app              # Set working directory (no layer produced)
ENV APP_ENV=production    # Store env var in image config (no layer produced)
COPY . /app               # Copy files from build context → produces a layer
RUN pip install flask     # Execute command in isolated root → produces a layer
CMD ["python", "main.py"] # Default command on container start (no layer produced)
```

| Instruction | Produces Layer | Notes |
|-------------|---------------|-------|
| `FROM` | No | Loads base image layers |
| `WORKDIR` | No | Updates build state only |
| `ENV` | No | Injected into all `RUN` commands and containers |
| `COPY` | **Yes** | Supports `*` and `**` globs |
| `RUN` | **Yes** | Executes inside isolated image filesystem |
| `CMD` | No | JSON array form required: `["exec", "arg"]` |

---

## CLI Reference

### Build an image

```bash
sudo python docksmith.py build -t myapp:latest .
sudo python docksmith.py build -t myapp:latest . --no-cache
```

**Example output — cold build:**
```
Step 1/4 : FROM alpine:3.18
Step 2/4 : WORKDIR /app
Step 3/4 : COPY . /app [CACHE MISS] 0.09s
Step 4/4 : RUN python setup.py [CACHE MISS] 3.82s
Successfully built sha256:a3f9b2c1 myapp:latest (3.91s)
```

**Example output — warm rebuild (no changes):**
```
Step 1/4 : FROM alpine:3.18
Step 2/4 : WORKDIR /app
Step 3/4 : COPY . /app [CACHE HIT]
Step 4/4 : RUN python setup.py [CACHE HIT]
Successfully built sha256:a3f9b2c1 myapp:latest (0.01s)
```

### List images

```bash
python docksmith.py images
```
```
NAME       TAG       ID              CREATED
myapp      latest    a3f9b2c1d4e5    2024-01-15T10:30:00
alpine     3.18      f1e2d3c4b5a6    2024-01-14T08:00:00
```

### Run a container

```bash
sudo python docksmith.py run myapp:latest
sudo python docksmith.py run myapp:latest python main.py
sudo python docksmith.py run -e APP_ENV=development myapp:latest
sudo python docksmith.py run -e KEY1=val1 -e KEY2=val2 myapp:latest
```

### Remove an image

```bash
python docksmith.py rmi myapp:latest
```

---

## Build Cache

The cache is deterministic and correct. Before every `COPY` or `RUN`, a cache key is computed as the SHA-256 of:

1. **Previous layer digest** — or base image manifest digest for the first layer-producing step
2. **Instruction text** — exactly as written in the Docksmithfile
3. **Current WORKDIR** — value at the time the instruction is reached
4. **Accumulated ENV state** — all key=value pairs sorted lexicographically by key
5. **COPY only** — SHA-256 of each source file's bytes, in lexicographic path order

**Cache behaviour:**

| Situation | Behaviour |
|-----------|-----------|
| Key matches + layer file on disk | `[CACHE HIT]` — skip execution |
| Key missing or layer file absent | `[CACHE MISS]` — execute and store |
| Any step is a miss | All subsequent steps are also misses (cascade) |
| `--no-cache` flag | Skip all lookups and writes |

**What invalidates the cache:**

- A source file changes (`COPY`)
- Instruction text changes
- `WORKDIR` value changes at that point in the file
- Any `ENV` value changes
- The `FROM` base image changes — invalidates all downstream steps via hash chain
- A layer file is missing from disk

---

## Container Isolation

Docksmith uses Linux kernel primitives directly — no Docker, no runc, no containerd.

**How it works:**
1. Extract all image layer tars in order into a temporary directory (later layers overwrite earlier ones)
2. Call `pick_isolator()` — uses `unshare --mount` + `chroot` to isolate the process into that root
3. Inject all image `ENV` vars, with `-e` overrides taking precedence
4. Set working directory to image `WorkingDir` (defaults to `/`)
5. Wait for process to exit, print exit code, delete temporary directory

**Critical:** The same `pick_isolator()` is used for both `RUN` during build and `docksmith run` — one primitive, two places.

**Verified isolation:** A file written inside a running container must not appear on the host filesystem. This is a live pass/fail requirement.

---

## Image Format

Every image is a JSON manifest stored in `~/.docksmith/images/`:

```json
{
  "name": "myapp",
  "tag": "latest",
  "digest": "sha256:a3f9b2c1...",
  "created": "2024-01-15T10:30:00",
  "config": {
    "Env": ["APP_ENV=production"],
    "Cmd": ["python", "main.py"],
    "WorkingDir": "/app"
  },
  "layers": [
    { "digest": "sha256:aaa...", "size": 2048, "createdBy": "alpine base layer" },
    { "digest": "sha256:bbb...", "size": 4096, "createdBy": "COPY . /app" },
    { "digest": "sha256:ccc...", "size": 8192, "createdBy": "RUN pip install flask" }
  ]
}
```

The manifest `digest` is computed over the canonical JSON — empty digest field, `sort_keys=True`, `separators=(',', ':')` — ensuring it is byte-for-byte identical across rebuilds when all steps are cache hits.

---

## Reproducible Builds

The same `Docksmithfile` and the same source files always produce identical layer digests and an identical manifest digest. Guaranteed by:

- **Sorted tar entries** — files added to each layer tar in lexicographic path order
- **Zeroed metadata** — `mtime=0`, `uid=0`, `gid=0`, `uname=''`, `gname=''` on every tar entry
- **Canonical manifest JSON** — `sort_keys=True`, `separators=(',', ':')` for digest computation
- **Preserved `created` timestamp** — when all steps are cache hits, the original timestamp is reused so the manifest digest stays identical

---

## Project Structure

```
docksmith/
├── docksmith.py                  # Entry point
├── cmd/
│   └── cli.py                    # Argument parsing and command routing (Garg)
├── internal/
│   ├── build/
│   │   ├── engine.py             # Build orchestrator — executes all 6 instructions (Garg)
│   │   ├── parser.py             # Docksmithfile parser (Wadhwa)
│   │   └── layers.py             # Reproducible delta tar creation (Shravan)
│   ├── cache/
│   │   └── cache.py              # Cache key computation and index persistence (Wadhwa)
│   ├── image/
│   │   └── manifest.py           # Image manifest model and SHA-256 digest (Shravan)
│   ├── store/
│   │   └── image_store.py        # Local image store — list, remove (Wadhwa)
│   └── runtime/
│       ├── isolate.py            # Linux namespace isolation — unshare + chroot (Sneh)
│       └── container.py          # Container assembler and launcher (Sneh)
├── gui/
│   ├── server.py                 # Flask REST + SSE backend (Sneh)
│   └── static/
│       └── index.html            # Web dashboard (Sneh)
├── sampleapp/
│   ├── Docksmithfile             # Uses all 6 instructions
│   ├── main.py                   # Sample application
│   └── setup.sh                  # Dependency setup
├── docksmith-import.py           # Base image import tool (Wadhwa)
├── setup-images.py               # One-time image setup (Wadhwa)
└── requirements.txt
```

---

## Demo Walkthrough

```bash
# 1. Cold build — all layer steps show [CACHE MISS]
sudo python docksmith.py build -t myapp:latest .

# 2. Warm rebuild — all steps show [CACHE HIT], completes near-instantly
sudo python docksmith.py build -t myapp:latest .

# 3. Edit a source file, then rebuild — affected step and all below show [CACHE MISS]
echo "# change" >> sampleapp/main.py
sudo python docksmith.py build -t myapp:latest .

# 4. List all images
python docksmith.py images

# 5. Run the container
sudo python docksmith.py run myapp:latest

# 6. Override an ENV variable at runtime
sudo python docksmith.py run -e APP_ENV=development myapp:latest

# 7. Verify isolation — file written inside must NOT appear on host
sudo python docksmith.py run myapp:latest sh -c "echo hello > /tmp/secret.txt"
ls /tmp/secret.txt   # Must not exist — PASS

# 8. Remove the image
python docksmith.py rmi myapp:latest
```

---

## GUI Dashboard

Start the web dashboard for a browser-based interface with real-time build log streaming:

```bash
pip install -r gui/requirements.txt
python gui/server.py
# Open http://localhost:5000
```

The GUI uses Server-Sent Events (SSE) to stream build output in real time.

---

## Out of Scope

The following are explicitly not implemented: networking, image registries, resource limits, multi-stage builds, bind mounts, detached containers, daemon processes, `EXPOSE`, `VOLUME`, `ADD`, `ARG`, `ENTRYPOINT`, `SHELL`.

---

## Acknowledgements

Built as a course project to deeply understand how container runtimes work at the OS level — content-addressed storage, deterministic build caching, and Linux process isolation.
