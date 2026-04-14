#!/usr/bin/env python3
"""
Docksmith GUI Server
A Flask-based web interface for the Docksmith container system.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Dependency check with helpful Windows-friendly error ──────────────────────
def _check_dep(module, install_hint):
    try:
        __import__(module)
    except ImportError:
        print(f"\nERROR: Python module '{module}' is not installed.")
        print(f"Fix it by running this EXACT command:")
        print(f"  {sys.executable} -m pip install {install_hint}")
        print(f"\n(This installs into the right Python: {sys.executable})")
        sys.exit(1)

_check_dep("flask", "flask flask-cors")
_check_dep("flask_cors", "flask-cors")

# Add parent dir to path so we can import docksmith internals
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from internal.store.image_store import (
    ImageStore,
    DOCKSMITH_DIR,
    IMAGES_DIR,
    LAYERS_DIR,
    CACHE_DIR,
    ensure_dirs,
)
from internal.image.manifest import ImageManifest

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ── helpers ───────────────────────────────────────────────────────────────────

def _docksmith_py():
    """Return path to docksmith.py."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docksmith.py")


def _run_docksmith(*args):
    """Run docksmith.py with given args, return (stdout, stderr, returncode)."""
    cmd = [sys.executable, _docksmith_py()] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(_docksmith_py()))
    return result.stdout, result.stderr, result.returncode


def _manifest_to_dict(m: ImageManifest) -> dict:
    short_id = m.digest.replace("sha256:", "")[:12]
    # Layer sizes
    total_size = sum(l.size for l in m.layers)
    return {
        "name": m.name,
        "tag": m.tag,
        "id": short_id,
        "digest": m.digest,
        "created": m.created,
        "layers": [
            {"digest": l.digest, "digest_short": l.digest.replace("sha256:", "")[:12],
             "size": l.size, "createdBy": l.createdBy}
            for l in m.layers
        ],
        "config": {
            "Env": m.config.Env,
            "Cmd": m.config.Cmd,
            "WorkingDir": m.config.WorkingDir,
        },
        "layer_count": len(m.layers),
        "total_size": total_size,
    }


def _store_stats() -> dict:
    ensure_dirs()
    images_dir = Path(IMAGES_DIR)
    layers_dir = Path(LAYERS_DIR)
    cache_dir = Path(CACHE_DIR)

    num_images = len(list(images_dir.glob("*.json")))
    layer_files = list(layers_dir.glob("*.tar"))
    num_layers = len(layer_files)
    total_layer_bytes = sum(f.stat().st_size for f in layer_files)

    cache_index = cache_dir / "index.json"
    num_cache_entries = 0
    if cache_index.exists():
        with open(cache_index) as f:
            try:
                num_cache_entries = len(json.load(f))
            except Exception:
                pass

    return {
        "num_images": num_images,
        "num_layers": num_layers,
        "total_layer_bytes": total_layer_bytes,
        "num_cache_entries": num_cache_entries,
        "docksmith_dir": DOCKSMITH_DIR,
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/stats")
def api_stats():
    return jsonify(_store_stats())


@app.route("/api/images")
def api_images():
    store = ImageStore()
    manifests = store._all_manifests()
    return jsonify([_manifest_to_dict(m) for m in manifests])


@app.route("/api/images/<name>/<tag>")
def api_image_detail(name, tag):
    store = ImageStore()
    m = store.load_manifest(f"{name}:{tag}")
    if m is None:
        return jsonify({"error": "Image not found"}), 404
    return jsonify(_manifest_to_dict(m))


@app.route("/api/images/<name>/<tag>", methods=["DELETE"])
def api_rmi(name, tag):
    stdout, stderr, rc = _run_docksmith("rmi", f"{name}:{tag}")
    if rc != 0:
        return jsonify({"error": stderr or stdout}), 400
    return jsonify({"message": stdout.strip()})


@app.route("/api/build", methods=["POST"])
def api_build():
    """Build an image. Returns SSE stream."""
    data = request.json or {}
    tag = data.get("tag", "myimage:latest")
    context = data.get("context", ".")
    no_cache = data.get("no_cache", False)

    # Resolve context relative to docksmith project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(context):
        context = os.path.join(project_root, context)

    args = ["build", "-t", tag]
    if no_cache:
        args.append("--no-cache")
    args.append(context)

    def generate():
        cmd = ["sudo", sys.executable, _docksmith_py()] + args
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=project_root,
        )
        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        yield f"data: {json.dumps({'done': True, 'returncode': proc.returncode})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/run", methods=["POST"])
def api_run():
    """Run a container. Returns SSE stream."""
    data = request.json or {}
    name_tag = data.get("name_tag", "")
    cmd_override = data.get("cmd", "")
    env_overrides = data.get("env", {})

    if not name_tag:
        return jsonify({"error": "name_tag required"}), 400

    args = ["run"]
    if isinstance(env_overrides, list):
        parsed = {}
        for e in env_overrides:
            if isinstance(e, dict) and e.get("key"):
                parsed[e["key"]] = e["value"]
            elif isinstance(e, str) and "=" in e:
                k2, _, v2 = e.partition("=")
                parsed[k2] = v2
        env_overrides = parsed
    elif not isinstance(env_overrides, dict):
        env_overrides = {}
    for k, v in env_overrides.items():
        args += ["-e", f"{k}={v}"]
    args.append(name_tag)
    if cmd_override:
        args.append(cmd_override)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def generate():
        cmd = [sys.executable, _docksmith_py()] + args
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
        )
        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        proc.wait()
        yield f"data: {json.dumps({'done': True, 'returncode': proc.returncode})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/cache")
def api_cache():
    cache_index = Path(CACHE_DIR) / "index.json"
    if not cache_index.exists():
        return jsonify([])
    with open(cache_index) as f:
        try:
            index = json.load(f)
        except Exception:
            return jsonify([])
    entries = []
    for key, digest in index.items():
        lp = Path(LAYERS_DIR) / (digest.replace("sha256:", "sha256_") + ".tar")
        entries.append({
            "key": key,
            "key_short": key.replace("sha256:", "")[:16],
            "digest": digest,
            "digest_short": digest.replace("sha256:", "")[:12],
            "exists": lp.exists(),
            "size": lp.stat().st_size if lp.exists() else 0,
        })
    return jsonify(entries)


@app.route("/api/layers")
def api_layers():
    layers_dir = Path(LAYERS_DIR)
    files = sorted(layers_dir.glob("*.tar"))
    result = []
    for f in files:
        digest = "sha256:" + f.stem.replace("sha256_", "")
        result.append({
            "digest": digest,
            "digest_short": digest.replace("sha256:", "")[:12],
            "size": f.stat().st_size,
            "path": str(f),
        })
    return jsonify(result)


@app.route("/api/contexts")
def api_contexts():
    """List available build contexts (directories with a Docksmithfile)."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    contexts = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("gui", "__pycache__")]
        if "Docksmithfile" in files:
            rel = os.path.relpath(root, project_root)
            contexts.append({"path": rel, "label": rel})
    return jsonify(contexts)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"🔧 Docksmith GUI running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
