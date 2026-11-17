"""Tiny stdlib HTTP helpers (no requests dependency)."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "alexai-ingest/0.1 (+podcast-rss-client)"


def get_bytes(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def download(url: str, dest: Path, timeout: int = 60, retries: int = 4) -> Path:
    """Stream `url` to `dest` via `dest.part`, resuming with a Range request when possible.
    The final rename is atomic, so `dest` only ever exists complete."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last = None
    for attempt in range(retries):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                mode = "ab" if have and resp.status == 206 else "wb"
                with open(part, mode) as fh:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
            part.replace(dest)
            return dest
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and part.exists():  # range not satisfiable: part is complete
                part.replace(dest)
                return dest
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]
