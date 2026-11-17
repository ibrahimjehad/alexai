"""YouTube adapter: STUB, not implemented yet.

Planned: resolve a video or playlist URL into entries (kind="youtube"). Note that the
ElevenLabs Scribe API accepts `source_url` (including YouTube), which may make a local
download unnecessary; decide when implementing. Do not add yt-dlp without approval."""
from __future__ import annotations

from pathlib import Path

_MSG = "youtube adapter is a stub: not implemented yet (see alexai/pipeline/adapters/youtube.py)"


def resolve(url_or_path: str, **_: object) -> list[dict]:
    raise NotImplementedError(_MSG)


def fetch(entry: dict, dest_dir: Path) -> Path:
    raise NotImplementedError(_MSG)
