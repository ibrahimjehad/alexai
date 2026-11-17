"""PDF adapter: local path or URL -> raw/pdfs/<id>.pdf -> per-page text.

Text extraction uses `pypdf` (optional extra: pip install -e '.[pdf]') and falls back to the
`pdftotext` CLI (poppler) when available."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ...manifest import new_entry
from ...util import AlexAIError
from ..http import download


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "doc"


def resolve(url_or_path: str, *, collection: str, author: str, id_prefix: str | None = None,
            title_regex: str | None = None, title_template: str | None = None) -> list[dict]:
    stem = Path(url_or_path.split("?")[0]).stem
    sid = id_prefix or f"{author}-{_slug(stem)}"
    title = title_template or stem.replace("-", " ").replace("_", " ")
    return [new_entry(id=sid, author=author, collection=collection, title=title, kind="pdf",
                      url=url_or_path)]


def fetch(entry: dict, dest_dir: Path) -> Path:
    dest = Path(dest_dir) / f"{entry['id']}.pdf"
    src = entry["url"]
    if src.startswith(("http://", "https://")):
        return download(src, dest)
    p = Path(src).expanduser()
    if not p.is_file():
        raise AlexAIError(f"pdf not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(p, tmp)
    tmp.replace(dest)
    return dest


def extract_pages(path: Path) -> tuple[str, list[str]]:
    """Return (extractor_name, [page_text, ...])."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        reader = PdfReader(str(path))
        return "pypdf", [(pg.extract_text() or "").strip() for pg in reader.pages]
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                             text=True, check=True).stdout
        return "pdftotext", [pg.strip() for pg in out.split("\f")]
    raise AlexAIError("no PDF text extractor: pip install -e '.[pdf]' (pypdf) or brew install poppler")
