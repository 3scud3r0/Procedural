"""Project schema, virtual modules and bounded file loading."""

from dataclasses import dataclass
from pathlib import Path
import json
import re
from .compiler import compile_source


@dataclass
class Project:
    files: dict[str, str]
    entry: str = "main.proc"
    seed: int | str = 42

    def validate(self):
        if not isinstance(self.files, dict) or not 1 <= len(self.files) <= 50:
            raise ValueError("project requires 1..50 files")
        if isinstance(self.seed, bool) or not isinstance(self.seed, (int, str)):
            raise ValueError("project seed must be integer or text")
        for name, source in self.files.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or path.suffix not in (".proc", ".py"):
                raise ValueError(f"invalid source path: {name}")
            if path.as_posix() != name or not re.fullmatch(
                r"[A-Za-z_]\w*(/[A-Za-z_]\w*)*\.(proc|py)", name
            ):
                raise ValueError(f"invalid source module: {name}")
            if not isinstance(source, str) or len(source.encode()) > 1_000_000:
                raise ValueError("each source must be text up to 1 MB")
        if sum(len(s.encode()) for s in self.files.values()) > 2_000_000:
            raise ValueError("project exceeds 2 MB")
        if self.entry not in self.files:
            raise ValueError("entry not present in project")
        modules = [name.rsplit(".", 1)[0].replace("/", ".") for name in self.files]
        if len(set(modules)) != len(modules):
            raise ValueError("ambiguous .proc/.py module names")
        if any(m in ("math", "procedural") for m in modules):
            raise ValueError("math and procedural are reserved capability modules")
        return self

    def to_dict(self):
        return {
            "schema": "procedural.project/1",
            "entry": self.entry,
            "seed": self.seed,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get("schema") != "procedural.project/1":
            raise ValueError("unsupported project schema")
        return cls(
            value["files"], value.get("entry", "main.proc"), value.get("seed", 42)
        ).validate()

    @classmethod
    def load(cls, path, seed=None):
        path = Path(path).resolve()
        if path.suffix == ".json":
            if path.stat().st_size > 2_100_000:
                raise ValueError("project JSON exceeds input budget")
            project = cls.from_dict(json.loads(path.read_text()))
        else:
            root = path.parent
            files = {}
            # Load sibling modules, never a full recursive repository scan.
            for candidate in sorted(root.iterdir()):
                if candidate.suffix in (".proc", ".py") and candidate.is_file():
                    resolved = candidate.resolve()
                    if not resolved.is_relative_to(root):
                        raise ValueError("source symlink escapes project root")
                    if candidate.stat().st_size > 1_000_000:
                        raise ValueError("source exceeds 1 MB")
                    files[candidate.name] = candidate.read_text()
            project = cls(files, path.name).validate()
        if seed is not None:
            project.seed = seed
        return project.validate()

    def compile(self):
        self.validate()
        programs = {
            name.rsplit(".", 1)[0].replace("/", "."): compile_source(source, name)
            for name, source in self.files.items()
        }
        return programs[self.entry.rsplit(".", 1)[0].replace("/", ".")], programs
