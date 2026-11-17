"""brain/manifest.json: the registry of every source and its pipeline stages."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .paths import layout
from .util import AlexAIError, atomic_write_json, is_kebab, read_json

SCHEMA_VERSION = 1
KINDS = ("podcast", "youtube", "pdf", "web")
STAGES = ("fetched", "transcribed", "distilled")
ENTRY_FIELDS = ("id", "author", "collection", "title", "kind", "url", "audio_url",
                "duration_sec", "sha256", "stages", "error")


def new_entry(*, id: str, author: str, collection: str, title: str, kind: str,
              url: str | None = None, audio_url: str | None = None,
              duration_sec: int | None = None) -> dict:
    entry = {
        "id": id, "author": author, "collection": collection, "title": title, "kind": kind,
        "url": url, "audio_url": audio_url, "duration_sec": duration_sec, "sha256": None,
        "stages": {s: None for s in STAGES}, "error": None,
    }
    validate_entry(entry)
    return entry


def validate_entry(entry: dict) -> list[str]:
    errs = []
    missing = [f for f in ENTRY_FIELDS if f not in entry]
    if missing:
        errs.append(f"missing fields {missing}")
    if not is_kebab(entry.get("id")):
        errs.append(f"id {entry.get('id')!r} is not kebab-case")
    if not is_kebab(entry.get("author")):
        errs.append(f"author {entry.get('author')!r} is not kebab-case")
    if entry.get("kind") not in KINDS:
        errs.append(f"kind {entry.get('kind')!r} not in {KINDS}")
    stages = entry.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        errs.append(f"stages must have exactly {STAGES}")
    if errs and "id" in entry:
        errs = [f"{entry['id']}: {e}" for e in errs]
    return errs


def _path(root=None) -> Path:
    return layout(root).manifest


def load(root=None) -> dict:
    data = read_json(_path(root), default=None)
    if data is None:
        return {"schema_version": SCHEMA_VERSION, "sources": []}
    return data


def save(data: dict, root=None) -> None:
    for e in data["sources"]:
        errs = validate_entry(e)
        if errs:
            raise AlexAIError("; ".join(errs))
    data["sources"].sort(key=lambda e: e["id"])
    atomic_write_json(_path(root), data)


@contextmanager
def locked(root=None) -> Iterator[dict]:
    """Read-modify-write the manifest under an exclusive file lock; saves on clean exit."""
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = load(root)
            yield data
            save(data, root)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def all_entries(root=None) -> list[dict]:
    return load(root)["sources"]


def get(source_id: str, root=None) -> dict:
    for e in all_entries(root):
        if e["id"] == source_id:
            return e
    raise AlexAIError(f"unknown source id {source_id!r}")


def upsert(entries: list[dict], root=None) -> dict:
    """Add new entries; for existing ids only refresh descriptive fields (never stages/sha)."""
    added, updated, unchanged = [], [], []
    with locked(root) as data:
        by_id = {e["id"]: e for e in data["sources"]}
        for new in entries:
            validate = validate_entry(new)
            if validate:
                raise AlexAIError("; ".join(validate))
            cur = by_id.get(new["id"])
            if cur is None:
                data["sources"].append(new)
                by_id[new["id"]] = new
                added.append(new["id"])
                continue
            changed = False
            for f in ("author", "collection", "title", "kind", "url", "audio_url", "duration_sec"):
                if new.get(f) is not None and cur.get(f) != new[f]:
                    cur[f] = new[f]
                    changed = True
            (updated if changed else unchanged).append(new["id"])
    return {"added": added, "updated": updated, "unchanged": unchanged}


def update(source_id: str, root=None, **changes) -> dict:
    """Atomically patch one entry. `stages` is merged, other keys replaced."""
    with locked(root) as data:
        for e in data["sources"]:
            if e["id"] == source_id:
                stages = changes.pop("stages", None)
                if stages:
                    unknown = set(stages) - set(STAGES)
                    if unknown:
                        raise AlexAIError(f"unknown stages {unknown}")
                    e["stages"].update(stages)
                e.update(changes)
                return dict(e)
    raise AlexAIError(f"unknown source id {source_id!r}")


def status(root=None) -> dict:
    entries = all_entries(root)
    counts = {s: sum(1 for e in entries if e["stages"][s]) for s in STAGES}
    return {
        "total": len(entries),
        "counts": counts,
        "errors": [{"id": e["id"], "error": e["error"]} for e in entries if e.get("error")],
        "sources": [
            {"id": e["id"], "title": e["title"], "kind": e["kind"],
             **{s: bool(e["stages"][s]) for s in STAGES}, "error": e.get("error")}
            for e in entries
        ],
    }
