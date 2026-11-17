"""ElevenLabs backend against a fixture response shaped like the documented API output."""
import json

import pytest

from alexai.pipeline import transcribe as stt
from alexai.util import AlexAIError


def _words(*items):
    out = []
    for i, (text, start, end) in enumerate(items):
        if i:
            out.append({"text": " ", "type": "spacing", "start": start, "end": start})
        out.append({"text": text, "type": "word", "start": start, "end": end, "logprob": -0.1,
                    "speaker_id": "speaker_0"})
    return out


FIXTURE = {
    "language_code": "en", "language_probability": 0.99, "text": "Hello world. (laughter) How are you?",
    "words": _words(("Hello", 0.0, 0.4), ("world.", 0.5, 0.9))
    + [{"text": "(laughter)", "type": "audio_event", "start": 1.0, "end": 1.5}]
    + _words(("How", 2.0, 2.2), ("are", 2.3, 2.4), ("you?", 2.5, 2.8)),
}


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "probe_duration", lambda p: 3.0)
    p = tmp_path / "a.mp3"
    p.write_bytes(b"ID3 fake")
    return p


def test_fixture_to_segments(audio, tmp_path):
    seen = {}

    def post(url, body, headers, timeout):
        seen.update(url=url, headers=headers, body=body)
        return 200, {}, json.dumps(FIXTURE).encode()

    be = stt.ElevenLabsBackend(api_key="test-key", post=post)
    res = stt.transcribe_file(audio, "src-1", tmp_path / "out", backend=be)
    doc = json.loads((tmp_path / "out/src-1.json").read_text())
    assert seen["url"] == "https://api.elevenlabs.io/v1/speech-to-text"
    assert seen["headers"]["xi-api-key"] == "test-key"
    assert b'name="model_id"\r\n\r\nscribe_v3' in seen["body"]
    assert b'name="timestamps_granularity"\r\n\r\nword' in seen["body"]
    assert doc["model"] == "scribe_v3" and doc["backend"] == "elevenlabs"
    assert doc["segments"] == [{"start": 0.0, "end": 0.9, "text": "Hello world."},
                               {"start": 2.0, "end": 2.8, "text": "How are you?"}]
    assert res["segments"] == 2


def test_retries_on_429_then_succeeds(audio):
    responses = [(429, {"Retry-After": "1"}, b'{"detail":"rate"}'), (503, {}, b"busy"),
                 (200, {}, json.dumps(FIXTURE).encode())]
    sleeps = []
    be = stt.ElevenLabsBackend(api_key="k", post=lambda *a: responses.pop(0), sleep=sleeps.append)
    units = be.transcribe(audio, "en")
    assert units[0]["text"].startswith("Hello") and len(sleeps) == 2


def test_client_error_not_retried(audio):
    calls = []

    def post(*a):
        calls.append(1)
        return 401, {}, b'{"detail":{"status":"invalid_api_key"}}'

    be = stt.ElevenLabsBackend(api_key="k", post=post, sleep=lambda s: None)
    with pytest.raises(AlexAIError, match="HTTP 401"):
        be.transcribe(audio, "en")
    assert len(calls) == 1


def test_large_file_is_split_and_offset(audio, monkeypatch):
    monkeypatch.setattr(stt.ElevenLabsBackend, "MAX_UPLOAD_BYTES", 1)
    monkeypatch.setattr(stt, "split_audio", lambda p, sec, d: [(p, 0.0), (p, 3600.0)])
    be = stt.ElevenLabsBackend(api_key="k", post=lambda *a: (200, {}, json.dumps(FIXTURE).encode()))
    segs = stt.group_segments(be.transcribe(audio, "en"))
    assert len(segs) == 4 and segs[2]["start"] == 3600.0 and segs[3]["end"] == 3602.8


def test_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    be = stt.ElevenLabsBackend(root=tmp_path)
    with pytest.raises(stt.ConfigError, match="set ELEVENLABS_API_KEY|ELEVENLABS_API_KEY is not set"):
        be.check()
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=abc123\n")
    be.check()
