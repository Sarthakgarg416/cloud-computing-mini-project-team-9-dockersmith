"""
Container runtime - assembles image filesystem and runs containers.
"""

import os
import sys
import tempfile
import subprocess as _sp
import shlex as _shlex
from typing import Dict, List, Optional

from internal.store.image_store import ImageStore, layer_path
from internal.build.layers import assemble_filesystem


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

        # Build environment
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
            for d in ["proc", "sys", "dev", "tmp"]:
                os.makedirs(os.path.join(rootfs, d), exist_ok=True)

            print(f"Assembling filesystem from {len(layer_paths)} layer(s)...")
            assemble_filesystem(layer_paths, rootfs)

            wd_abs = os.path.join(rootfs, workdir.lstrip("/"))
            os.makedirs(wd_abs, exist_ok=True)

            print(f"Starting container: {' '.join(command)}")
            print("-" * 40)

            # ✅ UPDATED: direct chroot execution (no pick_isolator)
            _cmd_str = " ".join(_shlex.quote(a) for a in command)

            result = _sp.run(
                ["chroot", rootfs, "/bin/sh", "-c",
                 f"cd {_shlex.quote(workdir)} 2>/dev/null || cd /; exec {_cmd_str}"],
                env=env,
                stdin=_sp.DEVNULL,
            )

            print("-" * 40)
            print(f"Container exited with code: {result.returncode}")

            if result.returncode != 0:
                raise SystemExit(result.returncode)