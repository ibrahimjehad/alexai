import json
from pathlib import Path

import pytest

from alexai import manifest
from alexai.pipeline import ingest
from alexai.pipeline import transcribe as stt
from alexai.pipeline.adapters import podcast
from alexai.util import AlexAIError

SID = "hormozi-100m-offers-p03"

FEED = b"""<?xml version="1.0"?><rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
<item><title>$100M Offers Audiobook Part 2</title><itunes:duration>3261</itunes:duration>
  <enclosure url="https://cdn.example.test/new2.mp3" type="audio/mpeg"/></item>
<item><title>$100M Offers Audiobook Part 2 | Ep 580</title><itunes:duration>3261</itunes:duration>
  <enclosure url="https://cdn.example.test/dup2.mp3" type="audio/mpeg"/></item>
<item><title>$100M Offers Audiobook part 1</title><itunes:duration>32:29</itunes:duration>
  <enclosure url="https://cdn.example.test/p1.mp3" type="audio/mpeg"/></item>
<item><title>Some other episode</title><enclosure url="https://cdn.example.test/x.mp3"/></item>
</channel></rss>"""


def test_podcast_resolve_matches_and_dedupes():
    entries = podcast.resolve("https://feed.example.test/rss", collection="100m-offers", author="alex-hormozi",
                              id_prefix="hormozi-100m-offers", title_regex=r"\$100M Offers Audiobook Part (\d+)",
                              feed_bytes=FEED)
    assert [e["id"] for e in entries] == ["hormozi-100m-offers-p01", "hormozi-100m-offers-p02"]
    assert entries[0]["duration_sec"] == 1949
    assert entries[1]["audio_url"].endswith("new2.mp3")
    assert all(v is None for e in entries for v in e["stages"].values())


def test_spotify_rejected():
    with pytest.raises(AlexAIError):
        podcast.resolve("https://open.spotify.com/show/abc", collection="c", author="a",
                        id_prefix="x", title_regex="(1)")


def test_upsert_is_idempotent_and_keeps_stages(root):
    manifest.update(SID, root, stages={"fetched": "2026-11-16T00:00:00+00:00"}, sha256="abc")
    again = manifest.new_entry(id=SID, author="alex-hormozi", collection="100m-offers", title="Part 3",
                               kind="podcast", url="https://example.test/feed.xml",
                               audio_url="https://example.test/p3.mp3", duration_sec=1654)
    res = manifest.upsert([again], root)
    assert res == {"added": [], "updated": [], "unchanged": [SID]}
    e = manifest.get(SID, root)
    assert e["stages"]["fetched"] and e["sha256"] == "abc"


def _fake_fetch(calls, payload=b"ID3 fake audio"):
    def fetch(entry, dest_dir):
        calls.append(entry["id"])
        p = Path(dest_dir) / f"{entry['id']}.mp3"
        p.write_bytes(payload)
        return p
    return fetch


def test_fetch_skips_when_done_and_hash_matches(root, monkeypatch):
    calls = []
    monkeypatch.setattr(podcast, "fetch", _fake_fetch(calls))
    assert ingest.fetch(SID, root=root)["status"] == "fetched"
    assert ingest.fetch(SID, root=root)["status"] == "skipped"
    assert calls == [SID]
    # corrupt the local file -> hash mismatch -> refetch
    (root / "raw/audio" / f"{SID}.mp3").write_bytes(b"corrupt")
    assert ingest.fetch(SID, root=root)["status"] == "fetched"
    assert ingest.fetch(SID, force=True, root=root)["status"] == "fetched"
    assert len(calls) == 3


class FakeBackend:
    name, model = "fake", "fake-1"

    def __init__(self):
        self.calls = 0

    def check(self):
        pass

    def transcribe(self, audio, language):
        self.calls += 1
        return [{"text": "Hello there. ", "start": 0.0, "end": 1.0},
                {"text": "Second sentence.", "start": 61.0, "end": 62.5}]


def test_transcribe_idempotent_and_writes_files(root, monkeypatch):
    monkeypatch.setattr(podcast, "fetch", _fake_fetch([]))
    fake = FakeBackend()
    monkeypatch.setattr(stt, "get_backend", lambda *a, **k: fake)
    monkeypatch.setattr(stt, "probe_duration", lambda p: 62.5)
    with pytest.raises(AlexAIError, match="not fetched"):
        ingest.transcribe(SID, root=root)
    ingest.fetch(SID, root=root)
    r = ingest.transcribe(SID, root=root)
    assert r["status"] == "transcribed"
    doc = json.loads((root / "raw/transcripts" / f"{SID}.json").read_text())
    assert doc["source_id"] == SID and doc["model"] == "fake-1" and doc["backend"] == "fake"
    assert doc["language"] == "en" and doc["segments"][0] == {"start": 0.0, "end": 1.0, "text": "Hello there."}
    txt = (root / "raw/transcripts" / f"{SID}.txt").read_text()
    assert "[00:00] Hello there." in txt and "[01:01] Second sentence." in txt
    assert ingest.transcribe(SID, root=root)["status"] == "skipped"
    assert fake.calls == 1
    assert manifest.get(SID, root)["stages"]["transcribed"]


def test_missing_key_gives_clear_error(root, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(podcast, "fetch", _fake_fetch([]))
    ingest.fetch(SID, root=root)
    with pytest.raises(stt.ConfigError, match="ELEVENLABS_API_KEY"):
        ingest.transcribe(SID, root=root)
    e = manifest.get(SID, root)
    assert e["stages"]["transcribed"] is None and e["error"] is None


def test_estimate(root):
    assert ingest.estimate(root)["total_sec"] == 1654
