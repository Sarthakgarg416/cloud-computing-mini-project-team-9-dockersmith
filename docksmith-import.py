#!/usr/bin/env python3
"""
docksmith-import: Import a pre-downloaded OCI/Docker image tarball into the local store.

Usage:
    python docksmith-import.py <image.tar> <name:tag>

The tar should be an OCI image layout or Docker image tarball (as saved by `docker save`).
This script extracts layers, writes them into ~/.docksmith/layers/, and creates a manifest.

Requirements: the image tar must already be downloaded. No network access is performed.
"""

import hashlib
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from internal.image.manifest import ImageManifest, ImageConfig, LayerEntry
from internal.store.image_store import ImageStore, layer_path, ensure_dirs
from internal.build.layers import create_layer_tar, digest_of_bytes


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def import_docker_tar(tar_path: str, name_tag: str):
    """Import a Docker-format image tarball (from docker save)."""
    ensure_dirs()
    store = ImageStore()

    if ":" in name_tag:
        name, tag = name_tag.split(":", 1)
    else:
        name, tag = name_tag, "latest"

    print(f"Importing {tar_path} as {name}:{tag} ...")

    with tempfile.TemporaryDirectory(prefix="docksmith_import_") as tmpdir:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(tmpdir)

        # Read manifest.json
        manifest_json_path = os.path.join(tmpdir, "manifest.json")
        if not os.path.exists(manifest_json_path):
            print("Error: not a Docker image tar (no manifest.json found)", file=sys.stderr)
            sys.exit(1)

        with open(manifest_json_path) as f:
            docker_manifest = json.load(f)

        # Take the first image entry because docker save can bundle multiple tags.
        entry = docker_manifest[0]
        config_file = entry.get("Config", "")
        layer_tars = entry.get("Layers", [])

        # Read config JSON
        config_data = {}
        config_path = os.path.join(tmpdir, config_file)
        if os.path.exists(config_path):
            with open(config_path) as f:
                config_data = json.load(f)

        container_config = config_data.get("config", {})
        env_list = container_config.get("Env") or []
        cmd_list = container_config.get("Cmd") or []
        workdir = container_config.get("WorkingDir") or ""

        # Process each layer tar
        layer_entries = []
        for layer_tar_rel in layer_tars:
            layer_tar_abs = os.path.join(tmpdir, layer_tar_rel)
            if not os.path.exists(layer_tar_abs):
                print(f"Warning: layer tar not found: {layer_tar_rel}", file=sys.stderr)
                continue

            # Re-create a reproducible tar for consistency
            # Extract to temp, then re-tar with our sorting/zeroing
            with tempfile.TemporaryDirectory(prefix="docksmith_layer_") as layer_tmp:
                with tarfile.open(layer_tar_abs, "r") as lt:
                    # Safe extract
                    lt.extractall(layer_tmp)

                tar_bytes = create_layer_tar(layer_tmp)

            digest = digest_of_bytes(tar_bytes)
            lp = layer_path(digest)
            if not os.path.exists(lp):
                with open(lp, "wb") as f:
                    f.write(tar_bytes)
                print(f"  Wrote layer {digest[:19]}... ({len(tar_bytes)} bytes)")
            else:
                print(f"  Layer {digest[:19]}... already exists, skipping.")

            layer_entries.append(
                LayerEntry(
                    digest=digest,
                    size=len(tar_bytes),
                    createdBy=f"imported from {os.path.basename(tar_path)}",
                )
            )

        # Build manifest
        manifest = ImageManifest(
            name=name,
            tag=tag,
            digest="",
            created=datetime.now(timezone.utc).isoformat(),
            config=ImageConfig(Env=env_list, Cmd=cmd_list, WorkingDir=workdir),
            layers=layer_entries,
        )
        manifest.finalize_digest()
        store.save_manifest(manifest)

        print(f"Successfully imported {name}:{tag}")
        print(f"  Digest: {manifest.digest}")
        print(f"  Layers: {len(layer_entries)}")


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <image.tar> <name:tag>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} alpine.tar alpine:3.18", file=sys.stderr)
        sys.exit(1)

    tar_path = sys.argv[1]
    name_tag = sys.argv[2]

    if not os.path.exists(tar_path):
        print(f"Error: file not found: {tar_path}", file=sys.stderr)
        sys.exit(1)

    import_docker_tar(tar_path, name_tag)


if __name__ == "__main__":
    main()
