"""Web article adapter: STUB, not implemented yet.

Planned: fetch an article URL, strip boilerplate to plain text, and store it as a
single-segment transcript (kind="web")."""
from __future__ import annotations

from pathlib import Path

_MSG = "web adapter is a stub: not implemented yet (see alexai/pipeline/adapters/web.py)"


def resolve(url_or_path: str, **_: object) -> list[dict]:
    raise NotImplementedError(_MSG)


def fetch(entry: dict, dest_dir: Path) -> Path:
    raise NotImplementedError(_MSG)
