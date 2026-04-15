"""
Build cache - deterministic cache key computation and hit/miss tracking.
"""

import hashlib
import json
import os
from typing import List, Optional

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


def _stable_env_state(env_state: dict) -> str:
    """Serialize environment state in a canonical order."""
    return "\n".join(f"{key}={value}" for key, value in sorted(env_state.items()))


def _stable_copy_hashes(copy_file_hashes: Optional[List[str]]) -> str:
    """Serialize COPY source hashes in a canonical order."""
    if not copy_file_hashes:
        return ""
    return "\n".join(sorted(copy_file_hashes))


def compute_cache_key(
    prev_digest: str,
    instruction_text: str,
    workdir: str,
    env_state: dict,
    copy_file_hashes: Optional[List[str]] = None,
) -> str:
    """
    Return the SHA-256 cache key for a build step.

    The key is derived from the five inputs defined by the cache spec:
    previous layer digest, full instruction text, current workdir, current
    environment state, and (for COPY) the hashes of all source files.
    """
    h = hashlib.sha256()

    # Keep field boundaries explicit so each input contributes independently.
    for value in (
        prev_digest,
        instruction_text,
        workdir,
        _stable_env_state(env_state),
        _stable_copy_hashes(copy_file_hashes),
    ):
        h.update(value.encode())
        h.update(b"\x00")

    return "sha256:" + h.hexdigest()


def lookup(cache_key: str) -> Optional[str]:
    """Return the layer digest if cache hit and layer file exists."""
    index = _load_index()
    digest = index.get(cache_key)
    if digest and os.path.exists(layer_path(digest)):
        return digest
    return None


def store(cache_key: str, layer_digest: str):
    """Record a cache entry."""
    index = _load_index()
    index[cache_key] = layer_digest
    _save_index(index)


def hash_file(path: str) -> str:
    """SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
