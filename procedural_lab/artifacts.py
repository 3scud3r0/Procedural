"""Artifacts with hashes and atomic directory publication."""

from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile


class ArtifactStore:
    def __init__(self, max_files=100, max_bytes=5_000_000):
        self.files = {}
        self.max_files, self.max_bytes = max_files, max_bytes

    def emit(self, name, value):
        path = Path(name)
        if (
            not isinstance(name, str)
            or not name
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() == "."
        ):
            raise ValueError("artifact requires a relative name without traversal")
        name = path.as_posix()
        if name in self.files:
            raise ValueError(f"duplicate artifact: {name}")
        if len(self.files) >= self.max_files:
            raise ValueError("artifact count limit exceeded")
        if isinstance(value, bytes):
            data = value
        elif isinstance(value, str):
            data = value.encode()
        else:
            data = (
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            ).encode()
        if sum(map(len, self.files.values())) + len(data) > self.max_bytes:
            raise ValueError("artifact byte limit exceeded")
        self.files[name] = data

    def manifest(self):
        return [
            {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(self.files.items())
        ]

    def publish(self, directory, metadata):
        """No partial runs and no overwrite: destination must not exist."""
        target = Path(directory).absolute()
        if target.exists():
            raise FileExistsError(f"output already exists: {target}")
        if "manifest.json" in self.files:
            raise ValueError("manifest.json is reserved by publication")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".procedural-", dir=target.parent))
        try:
            for name, data in self.files.items():
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest = {"schema": "procedural.run/1", **metadata, "artifacts": self.manifest()}
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            )
            if target.exists():
                raise FileExistsError(f"output already exists: {target}")
            os.rename(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target


def verify_run(directory):
    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema") != "procedural.run/1":
        raise ValueError("unsupported manifest schema")
    for record in manifest["artifacts"]:
        path = (root / record["name"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("manifest path escapes output")
        data = path.read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"artifact integrity failure: {record['name']}")
    return manifest
