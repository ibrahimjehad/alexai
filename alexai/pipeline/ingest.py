"""Ingestion pipeline: add -> fetch -> transcribe (-> distilled, marked after notes are written).

Every step is idempotent and resumable: a stage is skipped when its timestamp is set, its
output file exists and the audio hash still matches. `force=True` redoes it. State lives
only in brain/manifest.json and raw/, so an interrupted run simply continues next time."""
from __future__ import annotations

import time
from pathlib import Path

import yaml

from .. import manifest
from ..paths import layout
from ..util import AlexAIError, now_iso, read_json, sha256_file
from . import transcribe as stt
from .adapters import get_adapter, guess_kind
from .adapters import pdf as pdf_adapter

PRESETS_FILE = Path(__file__).with_name("presets.yaml")
AUDIO_KINDS = ("podcast", "youtube")


def presets() -> dict:
    return yaml.safe_load(PRESETS_FILE.read_text(encoding="utf-8")) or {}


# ---------------------------------------------------------------- add

def add(url_or_path: str | None = None, *, preset: str | None = None, kind: str | None = None,
        collection: str | None = None, author: str = "alex-hormozi", id_prefix: str | None = None,
        title_regex: str | None = None, title_template: str | None = None, root=None) -> dict:
    """Resolve a source (feed, pdf, ...) into manifest entries and register them."""
    expected = None
    if preset:
        p = presets().get(preset)
        if not p:
            raise AlexAIError(f"unknown preset {preset!r}; known: {sorted(presets())}")
        url_or_path = url_or_path or p["url"]
        kind, collection, author = p["kind"], p["collection"], p.get("author", author)
        id_prefix, title_regex = p.get("id_prefix"), p.get("title_regex")
        title_template, expected = p.get("title_template"), p.get("expected_parts")
    if not url_or_path:
        raise AlexAIError("give a URL/path or --preset")
    kind = kind or guess_kind(url_or_path)
    if not collection:
        raise AlexAIError("--collection is required (kebab-case)")
    entries = get_adapter(kind).resolve(url_or_path, collection=collection, author=author,
                                        id_prefix=id_prefix, title_regex=title_regex,
                                        title_template=title_template)
    result = manifest.upsert(entries, root)
    result["matched"] = [e["id"] for e in entries]
    if expected:
        have = {e["id"] for e in entries}
        result["missing"] = [f"{id_prefix}-p{i:02d}" for i in range(1, expected + 1)
                             if f"{id_prefix}-p{i:02d}" not in have]
    return result


# ---------------------------------------------------------------- files

def local_file(entry: dict, root=None) -> Path | None:
    lay = layout(root)
    folder = lay.pdfs if entry["kind"] == "pdf" else lay.audio
    if not folder.exists():
        return None
    for p in sorted(folder.glob(f"{entry['id']}.*")):
        if not p.name.endswith((".part", ".tmp")):
            return p
    return None


def transcript_paths(source_id: str, root=None) -> tuple[Path, Path]:
    t = layout(root).transcripts
    return t / f"{source_id}.json", t / f"{source_id}.txt"


# ---------------------------------------------------------------- fetch

def fetch(source_id: str, force: bool = False, root=None) -> dict:
    entry = manifest.get(source_id, root)
    existing = local_file(entry, root)
    if not force and entry["stages"]["fetched"] and existing and entry["sha256"]:
        if sha256_file(existing) == entry["sha256"]:
            return {"id": source_id, "status": "skipped", "path": str(existing)}
    lay = layout(root)
    dest_dir = lay.pdfs if entry["kind"] == "pdf" else lay.audio
    try:
        if force and existing:
            existing.unlink()
        path = get_adapter(entry["kind"]).fetch(entry, dest_dir)
        digest = sha256_file(path)
    except Exception as exc:
        manifest.update(source_id, root, error=f"fetch: {exc}")
        raise
    changes = {"sha256": digest, "error": None, "stages": {"fetched": now_iso()}}
    if entry["sha256"] and entry["sha256"] != digest:
        changes["stages"].update(transcribed=None, distilled=None)  # content changed downstream is stale
    manifest.update(source_id, root, **changes)
    return {"id": source_id, "status": "fetched", "path": str(path), "sha256": digest,
            "bytes": path.stat().st_size}


# ---------------------------------------------------------------- transcribe

def _transcript_current(entry: dict, root=None) -> bool:
    jpath, tpath = transcript_paths(entry["id"], root)
    if not (entry["stages"]["transcribed"] and jpath.exists() and tpath.exists()):
        return False
    doc = read_json(jpath, {})
    return bool(doc.get("audio_sha256")) and doc.get("audio_sha256") == entry["sha256"]


def transcribe(source_id: str, force: bool = False, backend: str | None = None,
               model: str | None = None, language: str = "en", root=None) -> dict:
    entry = manifest.get(source_id, root)
    if not force and _transcript_current(entry, root):
        return {"id": source_id, "status": "skipped", "path": str(transcript_paths(source_id, root)[0])}
    path = local_file(entry, root)
    if not entry["stages"]["fetched"] or path is None:
        raise AlexAIError(f"{source_id}: not fetched yet; run `ingest fetch {source_id}` first")
    out_dir = layout(root).transcripts
    try:
        if entry["kind"] == "pdf":
            t0 = time.monotonic()
            extractor, pages = pdf_adapter.extract_pages(path)
            segments = [{"start": i + 1, "end": i + 1, "text": " ".join(t.split())}
                        for i, t in enumerate(pages) if t.strip()]
            res = stt.write_transcript(out_dir, source_id, model=extractor, backend="pdf-text",
                                       language=language, segments=segments, audio_sha256=entry["sha256"],
                                       units="page", elapsed_sec=round(time.monotonic() - t0, 1))
        elif entry["kind"] in AUDIO_KINDS:
            be = stt.get_backend(backend, model, root)
            be.check()
            res = stt.transcribe_file(path, source_id, out_dir, backend=be, language=language,
                                      audio_sha256=entry["sha256"])
        else:
            raise AlexAIError(f"{source_id}: kind {entry['kind']!r} has no transcription step yet")
    except stt.ConfigError:
        raise  # configuration problem, not a source problem: do not mark the entry
    except Exception as exc:
        manifest.update(source_id, root, error=f"transcribe: {exc}")
        raise
    manifest.update(source_id, root, error=None, stages={"transcribed": now_iso()})
    return {"id": source_id, "status": "transcribed", **res}


# ---------------------------------------------------------------- batch / misc

def _select(ids: list[str] | None, all_: bool, root=None) -> list[str]:
    if all_:
        return [e["id"] for e in manifest.all_entries(root)]
    if not ids:
        raise AlexAIError("give source ids or --all")
    for i in ids:
        manifest.get(i, root)
    return ids


def run(ids: list[str] | None = None, all_: bool = False, force: bool = False,
        backend: str | None = None, model: str | None = None, root=None, log=None) -> dict:
    """fetch + transcribe each source sequentially. Per-source failures are recorded and the
    batch continues; a backend configuration error stops it before any work is done."""
    targets = _select(ids, all_, root)
    needs_stt = any(manifest.get(i, root)["kind"] in AUDIO_KINDS for i in targets)
    if needs_stt:
        stt.get_backend(backend, model, root).check()
    results, failed = [], []
    for sid in targets:
        try:
            f = fetch(sid, force=force, root=root)
            t = transcribe(sid, force=force, backend=backend, model=model, root=root)
            results.append({"id": sid, "fetch": f["status"], "transcribe": t["status"],
                            "elapsed_sec": t.get("elapsed_sec")})
        except stt.ConfigError:
            raise
        except Exception as exc:  # keep going, error is stored in the manifest
            failed.append({"id": sid, "error": str(exc)})
        if log:
            log((results + failed)[-1])
    return {"done": results, "failed": failed}


def mark_distilled(source_id: str, root=None) -> dict:
    entry = manifest.get(source_id, root)
    if not entry["stages"]["transcribed"]:
        raise AlexAIError(f"{source_id}: cannot mark distilled before it is transcribed")
    rec = layout(root).sources / f"{source_id}.md"
    if not rec.exists():
        raise AlexAIError(f"{source_id}: write brain/sources/{source_id}.md before marking distilled")
    return manifest.update(source_id, root, stages={"distilled": now_iso()})


def estimate(root=None) -> dict:
    """Audio still to transcribe (sum of duration_sec), for cost estimates."""
    pending = [e for e in manifest.all_entries(root)
               if e["kind"] in AUDIO_KINDS and not e["stages"]["transcribed"]]
    secs = sum(e["duration_sec"] or 0 for e in pending)
    unknown = [e["id"] for e in pending if not e["duration_sec"]]
    return {"pending_sources": len(pending), "total_sec": secs, "total_min": round(secs / 60, 1),
            "total_hours": round(secs / 3600, 3), "unknown_duration": unknown,
            "sources": [{"id": e["id"], "duration_sec": e["duration_sec"]} for e in pending]}
