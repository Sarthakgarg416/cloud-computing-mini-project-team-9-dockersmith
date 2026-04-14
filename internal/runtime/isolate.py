"""
Container isolation using Linux namespaces (unshare + chroot).
This is the single isolation primitive used for both RUN and docksmith run.
"""

import os
import shlex
import subprocess
import tempfile
from typing import Dict, List, Optional


def _copy_resolv(rootfs: str):
    resolv_dst = os.path.join(rootfs, "etc", "resolv.conf")
    try:
        os.makedirs(os.path.join(rootfs, "etc"), exist_ok=True)
        with open("/etc/resolv.conf") as src:
            content = src.read()
        with open(resolv_dst, "w") as dst:
            dst.write(content)
        if "nameserver" not in content:
            with open(resolv_dst, "w") as dst:
                dst.write("nameserver 8.8.8.8\nnameserver 8.8.4.4\n")
    except Exception:
        try:
            with open(resolv_dst, "w") as dst:
                dst.write("nameserver 8.8.8.8\nnameserver 8.8.4.4\n")
        except Exception:
            pass


def run_isolated(
    rootfs: str,
    command: List[str],
    workdir: str = "/",
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = False,
    interactive: bool = False,
) -> subprocess.CompletedProcess:
    if env is None:
        env = {}

    workdir = workdir if workdir else "/"
    _copy_resolv(rootfs)
    cmd_str = " ".join(shlex.quote(a) for a in command)

    bootstrap = f"""#!/bin/sh
set -e
mount -t proc proc '{rootfs}/proc' 2>/dev/null || true
mount -t sysfs sysfs '{rootfs}/sys' 2>/dev/null || true
mount --bind /dev '{rootfs}/dev' 2>/dev/null || true
exec chroot '{rootfs}' /bin/sh -c 'cd "$_WORKDIR" 2>/dev/null || cd /; exec "$@"' -- {cmd_str}
"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, prefix="docksmith_bootstrap_"
    ) as tf:
        tf.write(bootstrap)
        bootstrap_path = tf.name

    os.chmod(bootstrap_path, 0o700)

    container_env = dict(env)
    container_env["_WORKDIR"] = workdir
    if "PATH" not in container_env:
        container_env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    stdin = None if interactive else subprocess.DEVNULL

    try:
        result = subprocess.run(
            ["unshare", "--mount", "--pid", "--fork", "--", bootstrap_path],
            env=container_env,
            capture_output=capture_output,
            stdin=stdin,
        )
        return result
    finally:
        try:
            os.unlink(bootstrap_path)
        except OSError:
            pass


def run_isolated_simple(
    rootfs: str,
    command: List[str],
    workdir: str = "/",
    env: Optional[Dict[str, str]] = None,
    capture_output: bool = False,
    interactive: bool = False,
) -> subprocess.CompletedProcess:
    if env is None:
        env = {}

    workdir = workdir if workdir else "/"
    container_env = dict(env)
    container_env["_WORKDIR"] = workdir
    if "PATH" not in container_env:
        container_env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    _copy_resolv(rootfs)
    os.makedirs(os.path.join(rootfs, "proc"), exist_ok=True)

    cmd_str = " ".join(shlex.quote(a) for a in command)
    stdin = None if interactive else subprocess.DEVNULL

    return subprocess.run(
        ["chroot", rootfs, "/bin/sh", "-c",
         f"cd {shlex.quote(workdir)} 2>/dev/null || cd /; exec {cmd_str}"],
        env=container_env,
        capture_output=capture_output,
        stdin=stdin,
    )


# ✅ UPDATED: always use simple chroot
def pick_isolator(
    rootfs: str,
    command: List[str],
    workdir: str = "/",
    env=None,
    capture_output=False,
    interactive: bool = False,
):
    if env is None:
        env = {}

    return run_isolated_simple(
        rootfs,
        command,
        workdir=workdir,
        env=env,
        capture_output=capture_output,
        interactive=interactive,
    )