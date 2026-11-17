"""Source adapters. Every adapter module exposes the same two functions:

    resolve(url_or_path, *, collection, author, id_prefix=None, title_regex=None,
            title_template=None) -> list[dict]      # manifest entries (stages all null)
    fetch(entry, dest_dir: Path) -> Path             # download/copy the raw file, return its path

Ingest (alexai.pipeline.ingest) owns idempotency, hashing and manifest updates; adapters
only know how to talk to their kind of source."""
from __future__ import annotations

import importlib
from types import ModuleType

from ...util import AlexAIError

KINDS = ("podcast", "youtube", "pdf", "web")


def get_adapter(kind: str) -> ModuleType:
    if kind not in KINDS:
        raise AlexAIError(f"unknown source kind {kind!r}; expected one of {KINDS}")
    return importlib.import_module(f"{__name__}.{kind}")


def guess_kind(url_or_path: str) -> str:
    low = url_or_path.lower()
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    if low.endswith(".pdf"):
        return "pdf"
    if low.endswith((".xml", ".rss")) or "rss" in low or "feed" in low:
        return "podcast"
    return "web"
