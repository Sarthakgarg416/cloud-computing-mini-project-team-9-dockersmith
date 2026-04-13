"""
Image store - manages image manifests and layer files on disk.
"""

import os
import json
import shutil
from typing import Optional, List

from internal.image.manifest import ImageManifest

DOCKSMITH_DIR = os.path.expanduser("~/.docksmith")
IMAGES_DIR = os.path.join(DOCKSMITH_DIR, "images")
LAYERS_DIR = os.path.join(DOCKSMITH_DIR, "layers")
CACHE_DIR = os.path.join(DOCKSMITH_DIR, "cache")


def ensure_dirs():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(LAYERS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)


def _manifest_path(name: str, tag: str) -> str:
    return os.path.join(IMAGES_DIR, f"{name}_{tag}.json")


def _parse_name_tag(name_tag: str):
    if ":" in name_tag:
        name, tag = name_tag.split(":", 1)
    else:
        name, tag = name_tag, "latest"
    return name, tag


class ImageStore:
    def __init__(self):
        ensure_dirs()

    def save_manifest(self, manifest: ImageManifest):
        path = _manifest_path(manifest.name, manifest.tag)
        with open(path, "w") as f:
            json.dump(manifest.to_dict(), f, indent=2)

    def load_manifest(self, name_tag: str) -> Optional[ImageManifest]:
        name, tag = _parse_name_tag(name_tag)
        path = _manifest_path(name, tag)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return ImageManifest.from_dict(json.load(f))

    def list_images(self):
        print("TODO: not implemented yet")

    def remove_image(self, name_tag: str):
        print("TODO: not implemented yet")

    def _all_manifests(self) -> List[ImageManifest]:
        results = []
        for fn in sorted(os.listdir(IMAGES_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(IMAGES_DIR, fn)) as f:
                    try:
                        results.append(ImageManifest.from_dict(json.load(f)))
                    except Exception:
                        pass
        return results


def layer_path(digest: str) -> str:
    ensure_dirs()
    fname = digest.replace("sha256:", "sha256_")
    return os.path.join(LAYERS_DIR, fname + ".tar")


def cache_index_path() -> str:
    ensure_dirs()
    return os.path.join(CACHE_DIR, "index.json")
