"""
Image manifest data model.
"""

import json
import hashlib
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class LayerEntry:
    digest: str
    size: int
    createdBy: str


@dataclass
class ImageConfig:
    Env: List[str] = field(default_factory=list)
    Cmd: List[str] = field(default_factory=list)
    WorkingDir: str = ""


@dataclass
class ImageManifest:
    name: str
    tag: str
    digest: str
    created: str
    config: ImageConfig
    layers: List[LayerEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tag": self.tag,
            "digest": self.digest,
            "created": self.created,
            "config": {
                "Env": self.config.Env,
                "Cmd": self.config.Cmd,
                "WorkingDir": self.config.WorkingDir,
            },
            "layers": [
                {"digest": l.digest, "size": l.size, "createdBy": l.createdBy}
                for l in self.layers
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImageManifest":
        cfg = d.get("config", {})
        layers = [
            LayerEntry(digest=l["digest"], size=l["size"], createdBy=l["createdBy"])
            for l in d.get("layers", [])
        ]
        return cls(
            name=d["name"],
            tag=d["tag"],
            digest=d["digest"],
            created=d["created"],
            config=ImageConfig(
                Env=cfg.get("Env", []),
                Cmd=cfg.get("Cmd", []),
                WorkingDir=cfg.get("WorkingDir", ""),
            ),
            layers=layers,
        )

    def compute_digest(self) -> str:
        """Compute digest: serialize with digest="" then SHA-256."""
        d = self.to_dict()
        d["digest"] = ""
        canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def finalize_digest(self):
        d = self.to_dict()
        d["digest"] = ""
        canonical = json.dumps(d)  # missing sort_keys=True, separators
        self.digest = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

