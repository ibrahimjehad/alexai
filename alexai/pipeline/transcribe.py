"""Speech-to-text with pluggable backends, writing the fixed transcript format:

    raw/transcripts/<source-id>.json  {source_id, model, language, segments:[{start,end,text}],
                                       backend, audio_sha256, audio_duration_sec, elapsed_sec, created}
    raw/transcripts/<source-id>.txt   paragraphs, each prefixed with a [mm:ss] marker

Backends:
  elevenlabs (default)  ElevenLabs Speech to Text (Scribe), POST /v1/speech-to-text
  local                 mlx-whisper / faster-whisper, optional extra, imported lazily

A backend turns an audio file into "units": [{text, start, end}] in order, where `text`
carries its own leading/trailing whitespace. Grouping into sentence segments and paragraphs
is shared, so every backend yields the same file format."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Protocol

from ..paths import resolve_root
from ..util import AlexAIError, atomic_write_json, atomic_write_text, fmt_ts, now_iso

DEFAULT_BACKEND = "elevenlabs"


class ConfigError(AlexAIError):
    """Backend cannot run at all (missing key / package). Batch runs stop on this."""


class Backend(Protocol):
    name: str
    model: str

    def check(self) -> None: ...  # raise ConfigError if unusable

    def transcribe(self, audio: Path, language: str) -> list[dict]: ...


# ---------------------------------------------------------------- env / .env

def read_env(name: str, root=None) -> str | None:
    """Value from the environment, else from <root>/.env (KEY=VALUE lines). Never logged."""
    val = os.environ.get(name)
    if val:
        return val.strip()
    env_file = resolve_root(root) / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip().removeprefix("export ").strip() == name:
                v = v.strip().strip('"').strip("'")
                return v or None
    return None


# ---------------------------------------------------------------- audio helpers (ffmpeg)

def probe_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def split_audio(path: Path, chunk_sec: int, out_dir: Path) -> list[tuple[Path, float]]:
    """Split with ffmpeg (stream copy) into ~chunk_sec pieces. Returns [(chunk, offset_sec)],
    offsets taken from each chunk's probed duration so timestamps stay aligned."""
    if not shutil.which("ffmpeg"):
        raise ConfigError("ffmpeg is required to split large audio files")
    pattern = out_dir / f"chunk-%03d{path.suffix}"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-f", "segment",
                    "-segment_time", str(chunk_sec), "-c", "copy", "-reset_timestamps", "1",
                    str(pattern)], check=True)
    chunks, offset = [], 0.0
    for c in sorted(out_dir.glob(f"chunk-*{path.suffix}")):
        chunks.append((c, offset))
        offset += probe_duration(c) or chunk_sec
    return chunks


# ---------------------------------------------------------------- ElevenLabs Scribe

class ElevenLabsBackend:
    """ElevenLabs Speech to Text. Docs (checked 2026-11-16):
    https://elevenlabs.io/docs/api-reference/speech-to-text/convert
    POST https://api.elevenlabs.io/v1/speech-to-text, header `xi-api-key`, multipart with
    `model_id` + `file`; response {language_code, language_probability, text,
    words:[{text, type: word|spacing|audio_event, start, end, logprob, speaker_id}]}.
    Documented limits: file up to 5 GB, duration up to 15 h. Billed per hour of audio."""

    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/speech-to-text"
    # We split well below the documented 5 GB / 15 h limits to keep uploads small and retries cheap.
    MAX_UPLOAD_BYTES = 1_000_000_000
    MAX_DURATION_SEC = 4 * 3600
    CHUNK_SEC = 3600

    def __init__(self, model: str = "scribe_v3", root=None, api_key: str | None = None,
                 post: Callable[[str, bytes, dict, int], tuple[int, dict, bytes]] | None = None,
                 max_attempts: int = 5, base_delay: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self.model = model
        self.root = root
        self._api_key = api_key
        self._post = post or _urllib_post
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep

    def _key(self) -> str:
        key = self._api_key or read_env("ELEVENLABS_API_KEY", self.root)
        if not key:
            env_path = resolve_root(self.root) / ".env"
            raise ConfigError(f"ELEVENLABS_API_KEY is not set. Set ELEVENLABS_API_KEY in {env_path} "
                              "(copy .env.example) or export it in the environment.")
        return key

    def check(self) -> None:
        self._key()

    def transcribe(self, audio: Path, language: str) -> list[dict]:
        audio = Path(audio)
        duration = probe_duration(audio)
        too_big = audio.stat().st_size > self.MAX_UPLOAD_BYTES or (duration or 0) > self.MAX_DURATION_SEC
        if not too_big:
            return self._units_from_response(self._request(audio, language), 0.0)
        units: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="alexai-split-") as tmp:
            for chunk, offset in split_audio(audio, self.CHUNK_SEC, Path(tmp)):
                part = self._units_from_response(self._request(chunk, language), offset)
                if units and part and not units[-1]["text"].endswith((" ", "\n")):
                    part[0]["text"] = " " + part[0]["text"].lstrip()
                units.extend(part)
        return units

    def _request(self, audio: Path, language: str) -> dict:
        fields = {"model_id": self.model, "language_code": language,
                  "timestamps_granularity": "word", "tag_audio_events": "false", "diarize": "false"}
        body, ctype = _multipart(fields, "file", audio.name, audio.read_bytes())
        headers = {"xi-api-key": self._key(), "Content-Type": ctype, "Accept": "application/json"}
        last = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            try:
                status, resp_headers, data = self._post(self.URL, body, headers, 1800)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                status, resp_headers, data, last = None, {}, b"", f"network error: {exc}"
            if status == 200:
                return json.loads(data)
            if status is not None:
                last = f"HTTP {status}: {_err_text(data)}"
                if status not in (408, 409, 425, 429) and status < 500:
                    raise AlexAIError(f"ElevenLabs rejected the request ({last})")
            if attempt < self.max_attempts:
                retry_after = _retry_after(resp_headers)
                delay = retry_after if retry_after is not None else self.base_delay * 2 ** (attempt - 1)
                self._sleep(delay + random.uniform(0, 0.5))
        raise AlexAIError(f"ElevenLabs transcription failed after {self.max_attempts} attempts ({last})")

    @staticmethod
    def _units_from_response(resp: dict, offset: float) -> list[dict]:
        """words[] -> units. Spacing items are glued onto the previous word; audio events dropped."""
        if "words" not in resp and "transcripts" in resp:  # multichannel shape
            resp = resp["transcripts"][0]
        units: list[dict] = []
        for w in resp.get("words") or []:
            kind = w.get("type", "word")
            if kind == "spacing":
                if units:
                    units[-1]["text"] += w.get("text", " ")
                continue
            if kind != "word" or w.get("start") is None:
                continue
            units.append({"text": w["text"], "start": float(w["start"]) + offset,
                          "end": float(w.get("end") or w["start"]) + offset})
        if not units and resp.get("text"):
            units.append({"text": resp["text"], "start": offset, "end": offset})
        return units


def _multipart(fields: dict, file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"alexai-{uuid.uuid4().hex}"
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    out += content + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _urllib_post(url: str, body: bytes, headers: dict, timeout: int) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


def _retry_after(headers: dict) -> float | None:
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return min(float(v), 300.0)
            except ValueError:
                return None
    return None


def _err_text(data: bytes) -> str:
    try:
        obj = json.loads(data)
        detail = obj.get("detail", obj)
        return json.dumps(detail)[:300]
    except Exception:
        return (data or b"").decode("utf-8", "replace")[:300]


# ---------------------------------------------------------------- local whisper (optional)

class LocalWhisperBackend:
    """Optional offline backend: `pip install -e '.[local]'` (mlx-whisper on Apple Silicon)
    or install faster-whisper. Nothing is imported until used."""

    name = "local"

    def __init__(self, model: str | None = None, root=None):
        self.model = model or "mlx-community/whisper-large-v3-turbo"
        self._impl = None

    def check(self) -> None:
        try:
            import mlx_whisper  # type: ignore  # noqa: F401
            self._impl = "mlx"
            return
        except ImportError:
            pass
        try:
            import faster_whisper  # type: ignore  # noqa: F401
            self._impl = "faster"
            if self.model.startswith("mlx-community/"):
                self.model = "large-v3-turbo"
            return
        except ImportError:
            pass
        raise ConfigError("local backend needs mlx-whisper or faster-whisper: pip install -e '.[local]'")

    def transcribe(self, audio: Path, language: str) -> list[dict]:
        self.check()
        if self._impl == "mlx":
            import mlx_whisper  # type: ignore
            res = mlx_whisper.transcribe(str(audio), path_or_hf_repo=self.model, language=language)
            segs = res["segments"]
        else:
            from faster_whisper import WhisperModel  # type: ignore
            segs_iter, _ = WhisperModel(self.model).transcribe(str(audio), language=language)
            segs = [{"start": s.start, "end": s.end, "text": s.text} for s in segs_iter]
        return [{"text": s["text"], "start": float(s["start"]), "end": float(s["end"])} for s in segs]


BACKENDS = {"elevenlabs": ElevenLabsBackend, "local": LocalWhisperBackend}


def get_backend(name: str | None = None, model: str | None = None, root=None) -> Backend:
    name = name or os.environ.get("ALEXAI_STT_BACKEND") or DEFAULT_BACKEND
    if name not in BACKENDS:
        raise ConfigError(f"unknown transcription backend {name!r}; choose from {sorted(BACKENDS)}")
    kwargs = {"root": root}
    if model:
        kwargs["model"] = model
    return BACKENDS[name](**kwargs)


# ---------------------------------------------------------------- grouping + output

SENTENCE_END = (".", "?", "!", "…")


def group_segments(units: list[dict], max_sec: float = 30.0, gap_sec: float = 1.5) -> list[dict]:
    """Units -> sentence-sized segments. Break after sentence punctuation, on a pause longer
    than gap_sec, or when a segment exceeds max_sec."""
    segs: list[dict] = []
    cur: dict | None = None
    for u in units:
        if cur is not None and u["start"] - cur["end"] > gap_sec:
            segs.append(cur)
            cur = None
        if cur is None:
            cur = {"start": u["start"], "end": u["end"], "text": ""}
        cur["text"] += u["text"]
        cur["end"] = max(cur["end"], u["end"])
        stripped = u["text"].rstrip().rstrip('"\')”’')
        if stripped.endswith(SENTENCE_END) or cur["end"] - cur["start"] >= max_sec:
            segs.append(cur)
            cur = None
    if cur is not None:
        segs.append(cur)
    out = []
    for s in segs:
        text = " ".join(s["text"].split())
        if text:
            out.append({"start": round(s["start"], 2), "end": round(s["end"], 2), "text": text})
    return out


def paragraphs(segments: list[dict], target_sec: float = 45.0, max_sec: float = 90.0,
               pause_sec: float = 3.0) -> list[dict]:
    """Group segments into paragraphs of roughly target_sec, closing on a sentence end
    (or on a long pause)."""
    paras, cur = [], []
    for s in segments:
        if cur and s["start"] - cur[-1]["end"] > pause_sec:
            paras.append(cur)
            cur = []
        cur.append(s)
        span = cur[-1]["end"] - cur[0]["start"]
        if (span >= target_sec and s["text"].endswith(SENTENCE_END)) or span >= max_sec:
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)
    return [{"start": p[0]["start"], "text": " ".join(x["text"] for x in p)} for p in paras]


def render_txt(source_id: str, model: str, backend: str, segments: list[dict]) -> str:
    lines = [f"# {source_id} | {backend}:{model}", ""]
    for p in paragraphs(segments):
        lines += [f"[{fmt_ts(p['start'])}] {p['text']}", ""]
    return "\n".join(lines)


def write_transcript(out_dir: Path, source_id: str, *, model: str, backend: str, language: str,
                     segments: list[dict], **meta) -> dict:
    out_dir = Path(out_dir)
    doc = {"source_id": source_id, "model": model, "language": language, "segments": segments,
           "backend": backend, **meta, "created": now_iso()}
    atomic_write_json(out_dir / f"{source_id}.json", doc)
    atomic_write_text(out_dir / f"{source_id}.txt", render_txt(source_id, model, backend, segments))
    return {"json": str(out_dir / f"{source_id}.json"), "txt": str(out_dir / f"{source_id}.txt"),
            "segments": len(segments)}


def transcribe_file(audio: Path, source_id: str, out_dir: Path, *, backend: Backend,
                    language: str = "en", audio_sha256: str | None = None) -> dict:
    t0 = time.monotonic()
    units = backend.transcribe(Path(audio), language)
    segments = group_segments(units)
    if not segments:
        raise AlexAIError(f"{source_id}: transcription returned no text")
    elapsed = round(time.monotonic() - t0, 1)
    res = write_transcript(out_dir, source_id, model=backend.model, backend=backend.name,
                           language=language, segments=segments, audio_sha256=audio_sha256,
                           audio_duration_sec=probe_duration(Path(audio)), elapsed_sec=elapsed)
    return {**res, "elapsed_sec": elapsed}
