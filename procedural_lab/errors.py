"""Structured diagnostics shared by compiler, VM and command line."""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Location:
    file: str = "main.proc"
    line: int = 1
    column: int = 1


class Diagnostic(Exception):
    def __init__(self, code, message, location=None, frames=()):
        super().__init__(message)
        self.code = code
        self.message = str(message)
        self.location = location or Location()
        self.frames = list(frames)

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "location": asdict(self.location),
            "frames": self.frames,
        }

    def __str__(self):
        p = self.location
        return f"{p.file}:{p.line}:{p.column}: {self.code}: {self.message}"
