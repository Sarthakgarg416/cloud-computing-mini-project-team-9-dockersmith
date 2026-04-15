"""
Container runtime - assembles image filesystem and runs containers.
"""

import os
import sys
import tempfile
from typing import Dict, List, Optional

from internal.store.image_store import ImageStore, layer_path
from internal.build.layers import assemble_filesystem
from internal.runtime.isolate import pick_isolator


class ContainerRuntime:
    def __init__(self):
        self.store = ImageStore()

    def run(
        self,
        name_tag: str,
        cmd_override: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ):
        manifest = self.store.load_manifest(name_tag)
        if manifest is None:
            print(f"Error: image '{name_tag}' not found.", file=sys.stderr)
            raise SystemExit(1)

        # Resolve command
        if cmd_override:
            command = ["/bin/sh", "-c", cmd_override]
        elif manifest.config.Cmd:
            command = manifest.config.Cmd
        else:
            print(
                f"Error: no CMD defined in image '{name_tag}' and no command given.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Build environment: image ENV first, then overrides
        env = {}
        for pair in manifest.config.Env:
            k, _, v = pair.partition("=")
            env[k] = v
        if env_overrides:
            env.update(env_overrides)

        workdir = manifest.config.WorkingDir or "/"

        # Assemble filesystem
        layer_paths = [layer_path(l.digest) for l in manifest.layers]

        with tempfile.TemporaryDirectory(prefix="docksmith_rootfs_") as rootfs:
            # Create required dirs inside rootfs
            for d in ["proc", "sys", "dev", "tmp"]:
                os.makedirs(os.path.join(rootfs, d), exist_ok=True)

            print(f"Assembling filesystem from {len(layer_paths)} layer(s)...")
            assemble_filesystem(layer_paths, rootfs)

            # Ensure workdir exists
            wd_abs = os.path.join(rootfs, workdir.lstrip("/"))
            os.makedirs(wd_abs, exist_ok=True)

            print(f"Starting container: {' '.join(command)}")
            print("-" * 40)

            result = pick_isolator(
                rootfs,
                command,
                workdir=workdir,
                env=env,
            )

            print("-" * 40)
            print(f"Container exited with code: {result.returncode}")

            if result.returncode != 0:
                raise SystemExit(result.returncode)
