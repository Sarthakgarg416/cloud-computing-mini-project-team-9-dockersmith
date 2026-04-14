"""
Build engine - parses Docksmithfile and executes all instructions.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from internal.build.parser import parse, parse_cmd_args, parse_env_args, Instruction
from internal.build.layers import (
    create_layer_tar,
    digest_of_bytes,
    copy_files_to_delta,
    assemble_filesystem,
    apply_globs,
)
from internal.cache import cache as cache_mod
from internal.image.manifest import ImageManifest, ImageConfig, LayerEntry
from internal.store.image_store import ImageStore, layer_path
import subprocess as _sp

# Files written by the isolation setup that must never appear in a layer delta
_ISOLATION_FILES = {
    "etc/resolv.conf",
    "etc/hosts",
    "etc/hostname",
}


class BuildEngine:
    def __init__(self, context_dir: str, tag: str, no_cache: bool = False):
        self.context_dir = os.path.abspath(context_dir)
        self.tag = tag
        self.no_cache = no_cache
        self.store = ImageStore()

        if ":" in tag:
            self.name, self.image_tag = tag.split(":", 1)
        else:
            self.name = tag
            self.image_tag = "latest"

    def build(self):
        instructions = parse(self.context_dir)
        total_steps = len(instructions)
        start_total = time.time()

        # Build state
        base_manifest: Optional[ImageManifest] = None
        layers: List[LayerEntry] = []
        config = ImageConfig()
        workdir = ""
        env_state: Dict[str, str] = {}
        prev_digest = ""  # digest of previous layer (or base manifest digest for first layer-producing step)
        cache_busted = False  # once True, all subsequent steps are misses
        original_created: Optional[str] = None  # preserved for all-cache-hit rebuilds

        # Step numbering
        step_idx = 0

        for instr in instructions:
            step_idx += 1
            self._print_step(step_idx, total_steps, instr)

            if instr.name == "FROM":
                self._handle_from(instr, step_idx, total_steps)
                base_manifest = self.store.load_manifest(instr.args.strip())
                if base_manifest is None:
                    print(
                        f"Error: base image '{instr.args.strip()}' not found in local store.\n"
                        "Import it first with: docksmith-import (see README).",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                layers = list(base_manifest.layers)
                config = ImageConfig(
                    Env=list(base_manifest.config.Env),
                    Cmd=list(base_manifest.config.Cmd),
                    WorkingDir=base_manifest.config.WorkingDir,
                )
                workdir = base_manifest.config.WorkingDir or ""
                env_state = {}
                for pair in base_manifest.config.Env:
                    k, _, v = pair.partition("=")
                    env_state[k] = v
                prev_digest = base_manifest.digest

            elif instr.name == "WORKDIR":
                workdir = instr.args.strip()

            elif instr.name == "ENV":
                k, v = parse_env_args(instr.args)
                env_state[k] = v

            elif instr.name == "CMD":
                config.Cmd = parse_cmd_args(instr.args)

            elif instr.name == "COPY":
                raise NotImplementedError("COPY not implemented yet")

            elif instr.name == "RUN":
                raise NotImplementedError("RUN not implemented yet")

        total_elapsed = time.time() - start_total

        # Check if all steps were cache hits (for timestamp preservation)
        all_cache_hit = not cache_busted

        # Load existing manifest for created timestamp preservation
        # Reuse existing timestamp if: all cache hits OR image already exists (reproducibility)
        existing = self.store.load_manifest(f"{self.name}:{self.image_tag}")
        if existing is not None:
            created = existing.created
        else:
            created = datetime.now(timezone.utc).isoformat()

        # Finalize config
        config.WorkingDir = workdir
        config.Env = [f"{k}={v}" for k, v in sorted(env_state.items())]

        manifest = ImageManifest(
            name=self.name,
            tag=self.image_tag,
            digest="",
            created=created,
            config=config,
            layers=layers,
        )
        manifest.finalize_digest()
        self.store.save_manifest(manifest)

        short = manifest.digest.replace("sha256:", "")[:12]
        print(
            f"\nSuccessfully built sha256:{short} {self.name}:{self.image_tag} ({total_elapsed:.2f}s)"
        )

    # -------------------------------------------------------------------------
    # Instruction handlers
    # -------------------------------------------------------------------------

    def _print_step(self, idx: int, total: int, instr: Instruction):
        print(f"Step {idx}/{total} : {instr.name} {instr.args}")

    def _handle_from(self, instr: Instruction, idx: int, total: int):
        # FROM just prints - no cache status, no timing
        pass

    def _handle_copy(
        self,
        instr: Instruction,
        prev_digest: str,
        workdir: str,
        env_state: dict,
        current_layers: List[LayerEntry],
        cache_busted: bool,
    ) -> Tuple[Optional[LayerEntry], bool, float]:
        """Returns (layer_entry, cache_hit, elapsed_seconds)."""

        # Parse COPY src dest
        parts = instr.args.split(None, 1)
        if len(parts) != 2:
            print(f"Error: COPY requires <src> <dest>. Got: {instr.args!r}", file=sys.stderr)
            raise SystemExit(1)
        src_pattern, dest = parts

        # Compute file hashes for cache key
        matches = apply_globs(self.context_dir, src_pattern)
        file_hashes = []
        for path in sorted(matches):
            if os.path.isfile(path):
                rel = os.path.relpath(path, self.context_dir)
                file_hash = cache_mod.hash_file(path)
                file_hashes.append(f"{rel}:{file_hash}")
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    dirs.sort()
                    for fname in sorted(files):
                        fpath = os.path.join(root, fname)
                        rel = os.path.relpath(fpath, self.context_dir)
                        file_hash = cache_mod.hash_file(fpath)
                        file_hashes.append(f"{rel}:{file_hash}")

        cache_key = cache_mod.compute_cache_key(
            prev_digest=prev_digest,
            instruction_text=f"COPY {instr.args}",
            workdir=workdir,
            env_state=env_state,
            copy_file_hashes=file_hashes,
        )

        # Cache lookup
        if not self.no_cache and not cache_busted:
            hit_digest = cache_mod.lookup(cache_key)
            if hit_digest:
                lp = layer_path(hit_digest)
                size = os.path.getsize(lp)
                print(f"  [CACHE HIT]")
                entry = LayerEntry(digest=hit_digest, size=size, createdBy=f"COPY {instr.args}")
                return entry, True, 0.0

        # Cache miss - execute
        t0 = time.time()
        print(f"  [CACHE MISS]", end="", flush=True)

        with tempfile.TemporaryDirectory(prefix="docksmith_delta_") as delta_dir:
            # Ensure workdir exists in delta if set
            if workdir:
                os.makedirs(os.path.join(delta_dir, workdir.lstrip("/")), exist_ok=True)

            copy_files_to_delta(self.context_dir, src_pattern, dest, delta_dir)

            tar_bytes = create_layer_tar(delta_dir)

        digest = digest_of_bytes(tar_bytes)
        lp = layer_path(digest)
        if not os.path.exists(lp):
            with open(lp, "wb") as f:
                f.write(tar_bytes)

        elapsed = time.time() - t0
        print(f" {elapsed:.2f}s")

        if not self.no_cache:
            cache_mod.store(cache_key, digest)

        entry = LayerEntry(digest=digest, size=len(tar_bytes), createdBy=f"COPY {instr.args}")
        return entry, False, elapsed

    def _handle_run(
        self,
        instr: Instruction,
        prev_digest: str,
        workdir: str,
        env_state: dict,
        current_layers: List[LayerEntry],
        base_manifest: Optional[ImageManifest],
        cache_busted: bool,
    ) -> Tuple[Optional[LayerEntry], bool, float]:
        """Returns (layer_entry, cache_hit, elapsed_seconds)."""

        cache_key = cache_mod.compute_cache_key(
            prev_digest=prev_digest,
            instruction_text=f"RUN {instr.args}",
            workdir=workdir,
            env_state=env_state,
        )

        # Cache lookup
        if not self.no_cache and not cache_busted:
            hit_digest = cache_mod.lookup(cache_key)
            if hit_digest:
                lp = layer_path(hit_digest)
                size = os.path.getsize(lp)
                print(f"  [CACHE HIT]")
                entry = LayerEntry(digest=hit_digest, size=size, createdBy=f"RUN {instr.args}")
                return entry, True, 0.0

        # Cache miss - execute RUN inside the assembled filesystem
        t0 = time.time()
        print(f"  [CACHE MISS]", end="", flush=True)

        layer_paths_so_far = [layer_path(l.digest) for l in current_layers]

        with tempfile.TemporaryDirectory(prefix="docksmith_rootfs_run_") as rootfs:
            # Create required dirs
            for d in ["proc", "sys", "dev", "tmp"]:
                os.makedirs(os.path.join(rootfs, d), exist_ok=True)

            # Assemble all layers so far
            assemble_filesystem(layer_paths_so_far, rootfs)

            # Ensure workdir exists
            if workdir:
                os.makedirs(os.path.join(rootfs, workdir.lstrip("/")), exist_ok=True)

            # Build env for the RUN command
            env = {}
            for pair in (base_manifest.config.Env if base_manifest else []):
                k, _, v = pair.partition("=")
                env[k] = v
            env.update(env_state)
            if "PATH" not in env:
                env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

            command = ["/bin/sh", "-c", instr.args]

            # Snapshot rootfs BEFORE isolation setup writes any files (resolv.conf etc)
            before_files = _all_files(rootfs)

            _cmd_str = " ".join(__import__("shlex").quote(a) for a in command)
            result = _sp.run(
                ["chroot", rootfs, "/bin/sh", "-c",
                f"cd {__import__('shlex').quote(workdir or '/')} 2>/dev/null || cd /; exec {_cmd_str}"],
                env=env, stdin=_sp.DEVNULL,
            )

            if result.returncode != 0:
                print(
                    f"\nError: RUN command failed with exit code {result.returncode}: {instr.args}",
                    file=sys.stderr,
                )
                raise SystemExit(result.returncode)

            # Compute delta: files added by RUN, excluding isolation-injected files
            after_files = _all_files(rootfs)
            delta_paths = sorted(after_files - before_files - _ISOLATION_FILES)

            # Build delta tar
            with tempfile.TemporaryDirectory(prefix="docksmith_delta_") as delta_dir:
                for rel_path in sorted(delta_paths):
                    src = os.path.join(rootfs, rel_path)
                    dst = os.path.join(delta_dir, rel_path)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                    elif os.path.isdir(src):
                        os.makedirs(dst, exist_ok=True)

                tar_bytes = create_layer_tar(delta_dir)

        digest = digest_of_bytes(tar_bytes)
        lp = layer_path(digest)
        if not os.path.exists(lp):
            with open(lp, "wb") as f:
                f.write(tar_bytes)

        elapsed = time.time() - t0
        print(f" {elapsed:.2f}s")

        if not self.no_cache:
            cache_mod.store(cache_key, digest)

        entry = LayerEntry(digest=digest, size=len(tar_bytes), createdBy=f"RUN {instr.args}")
        return entry, False, elapsed


def _all_files(rootfs: str) -> set:
    """Return set of all relative file paths currently in rootfs."""
    result = set()
    for root, dirs, files in os.walk(rootfs):
        dirs.sort()
        for fname in sorted(files):
            abspath = os.path.join(root, fname)
            rel = os.path.relpath(abspath, rootfs)
            result.add(rel)
    return result