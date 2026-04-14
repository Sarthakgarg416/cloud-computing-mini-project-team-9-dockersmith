"""
Build cache - deterministic cache key computation and hit/miss tracking.
"""

import hashlib
import json
import os
from typing import Optional, List

from internal.store.image_store import cache_index_path, layer_path


def _load_index() -> dict:
    path = cache_index_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_index(index: dict):
    path = cache_index_path()
    with open(path, "w") as f:
        json.dump(index, f, indent=2)


def compute_cache_key(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_state: dict,
    copy_file_hashes: Optional[List[str]] = None,
) -> str:
    """
    Compute a deterministic cache key from all relevant inputs.
    """
    h = hashlib.sha256()
    h.update(prev_digest.encode())
    h.update(b"\x00")
    h.update(instruction_text.encode())
    h.update(b"\x00")
    h.update(workdir.encode())
    h.update(b"\x00")

    # ENV: lexicographically sorted key=value pairs
    env_sorted = sorted(f"{k}={v}" for k, v in env_state.items())
    env_str = "\n".join(env_sorted)
    h.update(env_str.encode())
    h.update(b"\x00")

    # COPY: sorted file hashes
    if copy_file_hashes:
        for fh in sorted(copy_file_hashes):
            h.update(fh.encode())
            h.update(b"\x00")

    return "sha256:" + h.hexdigest()


def lookup(cache_key: str) -> Optional[str]:
    return None


def store(cache_key: str, layer_digest: str):
    pass


def hash_file(path: str) -> str:
    """SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
