"""Fixed schemas for brain notes and source records (validation only, no I/O)."""
from __future__ import annotations

import datetime as _dt

from .manifest import KINDS
from .util import is_kebab

NOTE_TYPES = ("framework", "concept", "tactic", "example", "definition")
NOTE_REQUIRED = ("id", "type", "title", "author", "topics", "sources", "related", "updated")
# Optional index-time enrichment: plain-language questions the note answers and everyday
# alternative names for the idea. Both are indexed by search as their own fields.
NOTE_OPTIONAL = ("questions", "aliases")
NOTE_FIELDS = NOTE_REQUIRED + NOTE_OPTIONAL
QUESTIONS_EXPECTED_TYPES = ("framework", "tactic", "definition", "concept")
QUESTIONS_RANGE = (3, 6)
SOURCE_REQUIRED = ("id", "author", "collection", "title", "kind", "url", "duration_sec", "notes")


def _kebab_list(value, field, errs, allow_empty=True):
    if not isinstance(value, list):
        errs.append(f"{field} must be a list")
        return
    if not value and not allow_empty:
        errs.append(f"{field} must not be empty")
    for v in value:
        if not is_kebab(v):
            errs.append(f"{field} item {v!r} is not kebab-case")


def _string_list(value, field, errs):
    if not isinstance(value, list):
        errs.append(f"{field} must be a list of strings")
        return
    for v in value:
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{field} item {v!r} must be a non-empty string")


def validate_note_meta(meta: dict, filename_stem: str | None = None) -> list[str]:
    errs: list[str] = []
    for f in NOTE_REQUIRED:
        if f not in meta:
            errs.append(f"missing field '{f}'")
    extra = set(meta) - set(NOTE_FIELDS)
    if extra:
        errs.append(f"unknown fields {sorted(extra)}")
    if "id" in meta:
        if not is_kebab(meta["id"]):
            errs.append(f"id {meta['id']!r} is not kebab-case")
        if filename_stem is not None and meta["id"] != filename_stem:
            errs.append(f"id {meta['id']!r} does not match filename {filename_stem!r}")
    for f in NOTE_OPTIONAL:
        if f in meta:
            _string_list(meta[f], f, errs)
    if "type" in meta and meta["type"] not in NOTE_TYPES:
        errs.append(f"type {meta['type']!r} not in {NOTE_TYPES}")
    if "title" in meta and (not isinstance(meta["title"], str) or not meta["title"].strip()):
        errs.append("title must be a non-empty string")
    if "author" in meta and not is_kebab(meta["author"]):
        errs.append(f"author {meta['author']!r} is not kebab-case")
    if "topics" in meta:
        _kebab_list(meta["topics"], "topics", errs, allow_empty=False)
    if "related" in meta:
        _kebab_list(meta["related"], "related", errs)
    if "sources" in meta:
        srcs = meta["sources"]
        if not isinstance(srcs, list) or not srcs:
            errs.append("sources must be a non-empty list")
        else:
            for s in srcs:
                if not isinstance(s, dict) or set(s) != {"id", "ref"}:
                    errs.append(f"sources item {s!r} must have exactly 'id' and 'ref'")
                    continue
                if not is_kebab(s["id"]):
                    errs.append(f"sources id {s['id']!r} is not kebab-case")
                if not isinstance(s["ref"], str) or not s["ref"].strip():
                    errs.append(f"sources ref for {s['id']!r} must be a non-empty string")
    if "updated" in meta:
        u = meta["updated"]
        if isinstance(u, str):
            try:
                _dt.date.fromisoformat(u)
            except ValueError:
                errs.append(f"updated {u!r} is not YYYY-MM-DD")
        elif not isinstance(u, _dt.date):
            errs.append("updated must be a date YYYY-MM-DD")
    return errs


def note_meta_warnings(meta: dict) -> list[str]:
    """Non-fatal advice about a note's frontmatter (enrichment coverage)."""
    warns: list[str] = []
    qs = meta.get("questions")
    if meta.get("type") in QUESTIONS_EXPECTED_TYPES and not qs:
        warns.append(f"{meta['type']} note has no 'questions' (plain-language questions it answers)")
    elif isinstance(qs, list) and qs and not QUESTIONS_RANGE[0] <= len(qs) <= QUESTIONS_RANGE[1]:
        warns.append(f"questions has {len(qs)} items; aim for {QUESTIONS_RANGE[0]}-{QUESTIONS_RANGE[1]}")
    return warns


def validate_source_meta(meta: dict, filename_stem: str | None = None) -> list[str]:
    errs: list[str] = []
    for f in SOURCE_REQUIRED:
        if f not in meta:
            errs.append(f"missing field '{f}'")
    extra = set(meta) - set(SOURCE_REQUIRED)
    if extra:
        errs.append(f"unknown fields {sorted(extra)}")
    if "id" in meta:
        if not is_kebab(meta["id"]):
            errs.append(f"id {meta['id']!r} is not kebab-case")
        if filename_stem is not None and meta["id"] != filename_stem:
            errs.append(f"id {meta['id']!r} does not match filename {filename_stem!r}")
    if "author" in meta and not is_kebab(meta["author"]):
        errs.append(f"author {meta['author']!r} is not kebab-case")
    if "kind" in meta and meta["kind"] not in KINDS:
        errs.append(f"kind {meta['kind']!r} not in {KINDS}")
    if "duration_sec" in meta and meta["duration_sec"] is not None and not isinstance(meta["duration_sec"], int):
        errs.append("duration_sec must be an integer or null")
    if "notes" in meta:
        _kebab_list(meta["notes"], "notes", errs)
    return errs
