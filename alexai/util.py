"""Small shared helpers: atomic writes, frontmatter, hashing, ids, time."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class AlexAIError(Exception):
    """Base error for all expected, user-facing failures."""


def is_kebab(value: Any) -> bool:
    return isinstance(value, str) and bool(KEBAB_RE.match(value)) and len(value) <= 120


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def today() -> str:
    return _dt.date.today().isoformat()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body). Raises AlexAIError if malformed."""
    if not text.startswith("---"):
        raise AlexAIError("missing YAML frontmatter (file must start with '---')")
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise AlexAIError("unterminated YAML frontmatter")
    head = parts[0][3:]
    body = parts[1]
    body = body[body.find("\n") + 1 :] if "\n" in body else ""
    try:
        meta = yaml.safe_load(head) or {}
    except yaml.YAMLError as exc:
        raise AlexAIError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise AlexAIError("frontmatter must be a mapping")
    return meta, body.lstrip("\n")


def dump_frontmatter(meta: dict, body: str) -> str:
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=None).strip()
    return f"---\n{head}\n---\n\n{body.strip()}\n"


def fmt_ts(seconds: float) -> str:
    """Seconds -> mm:ss (minutes are not wrapped into hours)."""
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def parse_duration(value: Any) -> int | None:
    """'1949', '32:29', '1:02:03' -> seconds."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        parts = [float(p) for p in value.split(":")]
    except ValueError:
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return int(total)
