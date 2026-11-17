"""Filesystem layout. Every public function accepts an optional `root`; when omitted the
root comes from $ALEXAI_ROOT or defaults to the repository folder. A server can point
`root` at any data directory without code changes."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def resolve_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root).resolve()
    env = os.environ.get("ALEXAI_ROOT")
    return Path(env).resolve() if env else DEFAULT_ROOT


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def brain(self) -> Path:
        return self.root / "brain"

    @property
    def notes(self) -> Path:
        return self.brain / "notes"

    @property
    def sources(self) -> Path:
        return self.brain / "sources"

    @property
    def manifest(self) -> Path:
        return self.brain / "manifest.json"

    @property
    def index_json(self) -> Path:
        return self.brain / "index.json"

    @property
    def index_md(self) -> Path:
        return self.brain / "index.md"

    @property
    def audio(self) -> Path:
        return self.root / "raw" / "audio"

    @property
    def transcripts(self) -> Path:
        return self.root / "raw" / "transcripts"

    @property
    def pdfs(self) -> Path:
        return self.root / "raw" / "pdfs"

    @property
    def projects(self) -> Path:
        return self.root / "projects"


def layout(root: str | Path | None = None) -> Layout:
    return Layout(resolve_root(root))
