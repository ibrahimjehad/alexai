"""Podcast adapter: public RSS feed -> episode entries -> enclosure MP3.

Only public feed enclosures are used. Never point this at Spotify or any DRM stream."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from ...manifest import new_entry
from ...util import AlexAIError, parse_duration
from ..http import download, get_bytes

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
BLOCKED_HOSTS = ("spotify.com", "scdn.co", "spotifycdn.com")


def _check_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        raise AlexAIError("Spotify URLs are not allowed (DRM). Use the podcast's public RSS feed.")


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        enc = it.find("enclosure")
        title = " ".join((it.findtext("title") or "").split())
        items.append({
            "title": title,
            "audio_url": enc.get("url") if enc is not None else None,
            "duration_sec": parse_duration(it.findtext(f"{ITUNES}duration")),
            "guid": it.findtext("guid"),
            "link": it.findtext("link"),
            "pub_date": it.findtext("pubDate"),
        })
    return items


def resolve(url_or_path: str, *, collection: str, author: str, id_prefix: str | None = None,
            title_regex: str | None = None, title_template: str | None = None,
            feed_bytes: bytes | None = None) -> list[dict]:
    """Match feed items whose (whitespace-normalised) title fully matches `title_regex`.
    The regex must capture the part number as group 1 (or a named group `part`); ids become
    f"{id_prefix}-p{part:02d}". Duplicate parts (re-uploads) keep the first, i.e. newest, item."""
    _check_url(url_or_path)
    if not (id_prefix and title_regex):
        raise AlexAIError("podcast resolve needs id_prefix and title_regex (or use a --preset)")
    data = feed_bytes
    if data is None:
        data = Path(url_or_path).read_bytes() if Path(url_or_path).exists() else get_bytes(url_or_path)
    rx = re.compile(title_regex, re.IGNORECASE)
    found: dict[int, dict] = {}
    for item in parse_feed(data):
        m = rx.fullmatch(item["title"])
        if not m or not item["audio_url"]:
            continue
        part = int(m.groupdict().get("part") or m.group(1))
        if part in found:
            continue
        _check_url(item["audio_url"])
        title = title_template.format(part=part, feed_title=item["title"]) if title_template else item["title"]
        found[part] = new_entry(
            id=f"{id_prefix}-p{part:02d}", author=author, collection=collection, title=title,
            kind="podcast", url=url_or_path, audio_url=item["audio_url"],
            duration_sec=item["duration_sec"],
        )
    return [found[p] for p in sorted(found)]


def fetch(entry: dict, dest_dir: Path) -> Path:
    url = entry.get("audio_url")
    if not url:
        raise AlexAIError(f"{entry['id']}: no audio_url")
    _check_url(url)
    ext = Path(urlparse(url).path).suffix.lower() or ".mp3"
    if ext not in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"):
        ext = ".mp3"
    return download(url, Path(dest_dir) / f"{entry['id']}{ext}")
