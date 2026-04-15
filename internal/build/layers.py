"""
Layer builder - creates reproducible tar delta layers.
"""

import fnmatch
import glob
import hashlib
import io
import os
import shutil
import tarfile
import tempfile
from typing import List, Tuple


def _sorted_tar_entries(src_dir: str) -> List[Tuple[str, str]]:
    """Return (arcname, abspath) pairs sorted lexicographically by arcname."""
    entries = []
    for root, dirs, files in os.walk(src_dir):
        dirs.sort()
        rel_root = os.path.relpath(root, src_dir)
        if rel_root != ".":
            entries.append((rel_root, root))
        for fname in sorted(files):
            abspath = os.path.join(root, fname)
            arcname = os.path.join(rel_root, fname) if rel_root != "." else fname
            entries.append((arcname, abspath))
    return sorted(entries, key=lambda x: x[0])


def create_layer_tar(delta_dir: str) -> bytes:
    """
    Create a reproducible tar from delta_dir.
    - Entries in sorted lexicographic order
    - Timestamps zeroed out for reproducibility
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        entries = _sorted_tar_entries(delta_dir)
        for arcname, abspath in entries:
            info = tar.gettarinfo(abspath, arcname=arcname)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            if info.isfile():
                with open(abspath, "rb") as f:
                    tar.addfile(info, f)
            else:
                tar.addfile(info)
    return buf.getvalue()



def digest_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def apply_globs(context_dir: str, pattern: str) -> List[str]:
    """
    Expand a glob pattern relative to the context_dir.
    Supports * and ** globs.
    Returns list of matching absolute paths.
    """
    # Use ** support
    full_pattern = os.path.join(context_dir, pattern)
    matches = glob.glob(full_pattern, recursive=True)
    return sorted(matches)


def copy_files_to_delta(
    context_dir: str,
    src_pattern: str,
    dest: str,
    delta_dir: str,
):
    """
    Copy files matching src_pattern from context into delta_dir at dest path.
    Creates parent directories as needed.
    """
    matches = apply_globs(context_dir, src_pattern)
    if not matches:
        raise FileNotFoundError(f"COPY: no files matched pattern '{src_pattern}'")

    # Determine dest inside delta_dir
    dest_in_delta = os.path.join(delta_dir, dest.lstrip("/"))

    if len(matches) == 1 and os.path.isfile(matches[0]):
        # Single file: dest may be a filename or directory
        if dest.endswith("/") or os.path.isdir(dest_in_delta):
            os.makedirs(dest_in_delta, exist_ok=True)
            shutil.copy2(matches[0], os.path.join(dest_in_delta, os.path.basename(matches[0])))
        else:
            os.makedirs(os.path.dirname(dest_in_delta) or ".", exist_ok=True)
            shutil.copy2(matches[0], dest_in_delta)
    else:
        # Multiple files or directories: dest must be a directory
        os.makedirs(dest_in_delta, exist_ok=True)
        for src in matches:
            rel = os.path.relpath(src, context_dir)
            target = os.path.join(dest_in_delta, rel)
            if os.path.isdir(src):
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)


def extract_layer(tar_path: str, dest_dir: str):
    """Extract a layer tar into dest_dir (later layers overwrite earlier)."""
    with tarfile.open(tar_path, "r") as tar:
        tar.extractall(dest_dir)


def assemble_filesystem(layer_paths: List[str], dest_dir: str):
    """Extract all layers in order into dest_dir."""
    for lp in layer_paths:
        extract_layer(lp, dest_dir)
