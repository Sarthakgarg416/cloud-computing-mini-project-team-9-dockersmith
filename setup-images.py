#!/usr/bin/env python3
"""
setup-images.py - Download and import base images into the Docksmith local store.

Run this ONCE before any builds. Requires Docker to be available for the initial pull.
After this script runs, Docksmith operates fully offline.

Usage:
    python setup-images.py
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


IMAGES = [
    ("alpine:3.18", "alpine:3.18"),
]


def check_docker():
    result = subprocess.run(["docker", "version"], capture_output=True)
    return result.returncode == 0


def pull_and_save(docker_tag: str, tar_path: str):
    print(f"  Pulling {docker_tag} ...")
    result = subprocess.run(["docker", "pull", docker_tag])
    if result.returncode != 0:
        print(f"Error: failed to pull {docker_tag}", file=sys.stderr)
        sys.exit(1)

    print(f"  Saving {docker_tag} to {tar_path} ...")
    result = subprocess.run(["docker", "save", "-o", tar_path, docker_tag])
    if result.returncode != 0:
        print(f"Error: failed to save {docker_tag}", file=sys.stderr)
        sys.exit(1)


def import_image(tar_path: str, name_tag: str):
    print(f"  Importing {tar_path} as {name_tag} ...")
    # Reuse the current interpreter so the import step sees the same Python environment.
    result = subprocess.run(
        [sys.executable, "docksmith-import.py", tar_path, name_tag]
    )
    if result.returncode != 0:
        print(f"Error: failed to import {tar_path}", file=sys.stderr)
        sys.exit(1)


def main():
    print("=" * 60)
    print("  Docksmith Base Image Setup")
    print("=" * 60)
    print()

    if not check_docker():
        print("Error: Docker is required for the initial image download.")
        print("Install Docker, pull the images, save them as tar files,")
        print("then import manually:")
        print()
        print("  docker pull alpine:3.18")
        print("  docker save -o alpine-3.18.tar alpine:3.18")
        print("  python docksmith-import.py alpine-3.18.tar alpine:3.18")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="docksmith_setup_") as tmpdir:
        for docker_tag, docksmith_tag in IMAGES:
            print(f"\nProcessing: {docker_tag}")
            # The tarball is only an intermediate handoff between docker save and import.
            tar_path = os.path.join(tmpdir, docker_tag.replace(":", "_").replace("/", "_") + ".tar")
            pull_and_save(docker_tag, tar_path)
            import_image(tar_path, docksmith_tag)

    print()
    print("=" * 60)
    print("  All base images imported successfully.")
    print("  You can now build and run containers offline.")
    print()
    print("  Try:")
    print("    python docksmith.py build -t myapp:latest sampleapp/")
    print("    python docksmith.py images")
    print("    python docksmith.py run myapp:latest")
    print("=" * 60)


if __name__ == "__main__":
    main()
