"""Meaning-based (embedding) search layer, optional.

Everything model-specific sits behind the small `Embedder` interface (model_id, dim,
embed_documents, embed_query). The default backend runs a local ONNX model through FastEmbed
(`pip install -e '.[semantic]'`); tests and servers can inject any object with the same shape via
`set_embedder`. Note vectors are derived data cached under `<root>/.cache/vectors/`, keyed by
note content hash + model id, so only changed notes are re-embedded. Scoring is brute-force cosine
over an in-memory numpy matrix (`VectorStore`), which is right at a few thousand vectors; a real
vector store can replace `VectorStore` without touching `search_brain`.

The model and the vectors are cached per process, so a long-running server pays the model load once.
Search never downloads anything: only `brain index` (allow_download=True) may fetch the model."""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from .paths import DEFAULT_ROOT, layout
from .util import AlexAIError, atomic_write_bytes, parse_frontmatter

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
ENABLE_HINT = "install the extra if needed (`.venv/bin/pip install -e '.[semantic]'`), then run `brain index`"
# Bump when the per-note embedding text changes: every cached vector is then rebuilt.
# "multi-v1": one vector for title+aliases+body plus one per question, note score = max.
# "single-v1": one vector for title+aliases+questions+body (kept for comparison).
RECIPE = "multi-v1"

_BGE_QUERY = "Represent this sentence for searching relevant passages: "
# Query / document prefixes as documented on each model card (FastEmbed does not add them).
MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    "BAAI/bge-small-en-v1.5": (_BGE_QUERY, ""),
    "BAAI/bge-base-en-v1.5": (_BGE_QUERY, ""),
    "BAAI/bge-large-en-v1.5": (_BGE_QUERY, ""),
    "snowflake/snowflake-arctic-embed-xs": (_BGE_QUERY, ""),
    "snowflake/snowflake-arctic-embed-s": (_BGE_QUERY, ""),
    "snowflake/snowflake-arctic-embed-m": (_BGE_QUERY, ""),
    "snowflake/snowflake-arctic-embed-l": (_BGE_QUERY, ""),
    "mixedbread-ai/mxbai-embed-large-v1": (_BGE_QUERY, ""),
    "ibm-granite/granite-embedding-small-english-r2": ("", ""),
    "nomic-ai/nomic-embed-text-v1.5": ("search_query: ", "search_document: "),
    "Qwen/Qwen3-Embedding-0.6B": (
        "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:", ""),
    "Qwen/Qwen3-Embedding-0.6B-Q": (
        "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:", ""),
}


class SemanticUnavailable(AlexAIError):
    """Raised when the semantic layer cannot run (extra not installed, model not downloaded, disabled)."""


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed_documents(self, texts: Sequence[str]): ...  # -> np.ndarray [n, dim], L2-normalised

    def embed_query(self, text: str): ...  # -> np.ndarray [dim], L2-normalised


def model_dir() -> Path:
    """Where downloaded models live: $ALEXAI_MODEL_DIR, else <repo>/models (gitignored)."""
    env = os.environ.get("ALEXAI_MODEL_DIR")
    return Path(env).expanduser().resolve() if env else DEFAULT_ROOT / "models"


def configured_model() -> str:
    return os.environ.get("ALEXAI_EMBED_MODEL") or DEFAULT_MODEL


def _normalise(mat):
    import numpy as np
    mat = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    return mat / np.maximum(norms, 1e-12)


class FastEmbedBackend:
    """Local ONNX embedding model via FastEmbed (onnxruntime + tokenizers, no PyTorch)."""

    def __init__(self, model_id: str | None = None, allow_download: bool = False, threads: int | None = None):
        self.model_id = model_id or configured_model()
        try:
            import numpy  # noqa: F401
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise SemanticUnavailable(f"the semantic extra is not installed ({exc.name})") from exc
        self.query_prefix, self.doc_prefix = MODEL_PREFIXES.get(self.model_id, ("", ""))
        if not allow_download:
            # FastEmbed logs ERROR lines when a model is not cached; a missing model just means
            # "semantic off" here, which status() reports, so keep the search output clean.
            try:
                from loguru import logger
                logger.disable("fastembed")
            except ImportError:
                pass
        t0 = time.perf_counter()
        try:
            self._model = TextEmbedding(model_name=self.model_id, cache_dir=str(model_dir()), threads=threads,
                                        local_files_only=not allow_download)
        except Exception as exc:  # noqa: BLE001 - fastembed raises many kinds; any failure means "off"
            hint = "run `brain index` to download it" if not allow_download else f"{type(exc).__name__}: {exc}"
            raise SemanticUnavailable(f"model {self.model_id} is not available ({hint})") from exc
        self.load_sec = time.perf_counter() - t0
        self.dim = int(self._model.embedding_size)

    def embed_documents(self, texts: Sequence[str]):
        if not texts:
            import numpy as np
            return np.zeros((0, self.dim), dtype=np.float32)
        # Batch texts of similar length together: a batch is padded to its longest text, so mixing
        # long note bodies with short questions would multiply the work.
        import numpy as np
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        vecs = list(self._model.embed([self.doc_prefix + texts[i] for i in order], batch_size=32))
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        out[order] = np.asarray(vecs, dtype=np.float32)
        return _normalise(out)

    def embed_query(self, text: str):
        return _normalise(next(iter(self._model.embed([self.query_prefix + text]))))


# ---------------------------------------------------------------- process-level backend

@dataclass
class _State:
    embedder: Embedder | None = None
    error: str | None = None
    injected: bool = False
    stores: dict = field(default_factory=dict)  # (cache path, model id) -> _Loaded


_STATE = _State()


def set_embedder(embedder: Embedder | None, reason: str = "semantic search disabled") -> None:
    """Inject a backend (tests, servers, an alternative model). None turns semantic search off."""
    _STATE.embedder, _STATE.injected = embedder, True
    _STATE.error = None if embedder is not None else reason
    _STATE.stores.clear()


def reset() -> None:
    """Forget any injected or loaded backend; the next call re-detects from the environment."""
    _STATE.embedder, _STATE.error, _STATE.injected = None, None, False
    _STATE.stores.clear()


def _disabled_by_env() -> bool:
    return os.environ.get("ALEXAI_SEMANTIC", "").strip().lower() in {"0", "off", "false", "no"}


def get_embedder(allow_download: bool = False) -> Embedder | None:
    """The process-wide embedder, loading it once. None (with `status()` saying why) when unavailable."""
    if _STATE.injected:
        return _STATE.embedder
    if _disabled_by_env():
        _STATE.error = "semantic search disabled by ALEXAI_SEMANTIC"
        return None
    want = configured_model()
    if _STATE.embedder is not None and _STATE.embedder.model_id == want:
        return _STATE.embedder
    if _STATE.error is not None and not allow_download:
        return None  # already failed this process; do not retry on every search
    try:
        _STATE.embedder, _STATE.error = FastEmbedBackend(want, allow_download=allow_download), None
    except SemanticUnavailable as exc:
        _STATE.embedder, _STATE.error = None, str(exc)
    return _STATE.embedder


def status() -> str | None:
    """Why semantic search is off, or None when it is on (call after get_embedder)."""
    return _STATE.error


# ---------------------------------------------------------------- note text

def note_texts(meta: dict, body: str) -> list[str]:
    """Texts embedded for one note; the note scores as the max cosine over them.

    Vector 0 is the note itself: title, aliases and body (models truncate at their own limit, so
    the identifying text goes first). Each `questions` entry gets its own vector, because a
    question is a short query-shaped text that a single long-passage vector would dilute."""
    head = str(meta.get("title") or "")
    aliases = [str(a) for a in meta.get("aliases") or []]
    if aliases:
        head += f" (also called: {', '.join(aliases)})"
    questions = [str(q) for q in meta.get("questions") or [] if str(q).strip()]
    if RECIPE.startswith("single"):  # alternative measured during design: one vector per note
        return [f"{head}\n" + "\n".join(questions) + f"\n\n{body.strip()}"]
    return [f"{head}\n\n{body.strip()}"] + questions


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(RECIPE.encode() + b"\0" + data).hexdigest()


# ---------------------------------------------------------------- vector store

class VectorStore:
    """Brute-force cosine search over L2-normalised rows; several rows may belong to one note."""

    def __init__(self, ids: list[str], matrix):
        import numpy as np
        self.ids = list(ids)
        self.matrix = np.asarray(matrix, dtype=np.float32)
        # position of each row among its note's rows (0 = the note text, n = question n-1)
        seen: dict[str, int] = {}
        self.offsets = []
        for nid in self.ids:
            self.offsets.append(seen.get(nid, 0))
            seen[nid] = seen.get(nid, 0) + 1

    def note_scores(self, qvec) -> dict[str, float]:
        return self.note_scores_best(qvec)[0]

    def note_scores_best(self, qvec) -> tuple[dict[str, float], dict[str, int | None]]:
        """(max cosine per note, index of the note's best-matching question or None)."""
        if not self.ids:
            return {}, {}
        sims = self.matrix @ qvec
        out: dict[str, float] = {}
        best_q: dict[str, int | None] = {}
        bq_sim: dict[str, float] = {}
        for nid, off, s in zip(self.ids, self.offsets, sims.tolist()):
            if s > out.get(nid, -2.0):
                out[nid] = s
            if off == 0:
                best_q.setdefault(nid, None)
            elif s > bq_sim.get(nid, -2.0):
                bq_sim[nid], best_q[nid] = s, off - 1
        return out, best_q


@dataclass
class _Loaded:
    hashes: dict[str, str]
    store: VectorStore


def vector_path(model_id: str, root=None) -> Path:
    slug = "".join(c if c.isalnum() or c in "-." else "_" for c in model_id)
    return layout(root).root / ".cache" / "vectors" / f"{slug}.npz"


def _read_cache(path: Path, embedder: Embedder) -> dict[str, tuple[str, object]]:
    """{note_id: (hash, rows)} from disk, or {} when missing, unreadable or for another model/recipe."""
    import numpy as np
    if not path.exists():
        return {}
    try:
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            if (meta.get("model_id"), meta.get("dim"), meta.get("recipe")) != (embedder.model_id, embedder.dim, RECIPE):
                return {}
            ids, hashes, vecs = z["ids"].tolist(), z["hashes"].tolist(), z["vecs"]
    except Exception:  # noqa: BLE001 - a corrupt cache is simply rebuilt
        return {}
    out: dict[str, tuple[str, list]] = {}
    for i, (nid, h) in enumerate(zip(ids, hashes)):
        out.setdefault(nid, (h, []))[1].append(vecs[i])
    return {nid: (h, np.asarray(rows, dtype=np.float32)) for nid, (h, rows) in out.items()}


def _write_cache(path: Path, embedder: Embedder, per_note: dict[str, tuple[str, object]]) -> None:
    import numpy as np
    ids, hashes, rows = [], [], []
    for nid in sorted(per_note):
        h, mat = per_note[nid]
        for r in mat:
            ids.append(nid); hashes.append(h); rows.append(r)
    vecs = np.asarray(rows, dtype=np.float32).reshape(len(rows), embedder.dim)
    meta = json.dumps({"model_id": embedder.model_id, "dim": embedder.dim, "recipe": RECIPE})
    buf = io.BytesIO()
    np.savez(buf, ids=np.asarray(ids, dtype=str), hashes=np.asarray(hashes, dtype=str), vecs=vecs,
             meta=np.asarray(meta))
    atomic_write_bytes(path, buf.getvalue())


def ensure_vectors(embedder: Embedder, root=None) -> tuple[VectorStore, dict]:
    """Bring the vector cache in line with brain/notes and return (store, stats).
    Only notes whose file content changed since they were embedded (or whose model/recipe differs)
    are re-embedded. Stats: {model, notes, vectors, embedded, path}."""
    import numpy as np
    lay = layout(root)
    path = vector_path(embedder.model_id, root)
    current: dict[str, tuple[str, Path]] = {}
    if lay.notes.exists():
        for p in sorted(lay.notes.glob("*.md")):
            if not p.name.startswith("."):
                current[p.stem] = (_file_hash(p.read_bytes()), p)
    hashes = {nid: h for nid, (h, _) in current.items()}
    key = (str(path), embedder.model_id)
    loaded = _STATE.stores.get(key)
    if loaded is not None and loaded.hashes == hashes:
        return loaded.store, {"model": embedder.model_id, "notes": len(hashes), "vectors": len(loaded.store.ids),
                              "embedded": 0, "path": str(path)}

    old = _read_cache(path, embedder)
    per_note: dict[str, tuple[str, object]] = {}
    todo_ids, todo_texts = [], []
    for nid, (h, p) in current.items():
        if nid in old and old[nid][0] == h:
            per_note[nid] = old[nid]
            continue
        try:
            meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        except AlexAIError:
            per_note[nid] = (h, np.zeros((0, embedder.dim), dtype=np.float32))
            continue
        for t in note_texts(meta, body):
            todo_ids.append(nid); todo_texts.append(t)
        per_note[nid] = (h, None)
    if todo_texts:
        vecs = np.asarray(embedder.embed_documents(todo_texts), dtype=np.float32)
        grouped: dict[str, list] = {}
        for nid, v in zip(todo_ids, vecs):
            grouped.setdefault(nid, []).append(v)
        for nid, rows in grouped.items():
            per_note[nid] = (per_note[nid][0], np.asarray(rows, dtype=np.float32))
    per_note = {nid: v for nid, v in per_note.items() if v[1] is not None}
    if todo_texts or set(old) != set(per_note) or not path.exists():
        _write_cache(path, embedder, per_note)

    ids, rows = [], []
    for nid in sorted(per_note):
        for r in per_note[nid][1]:
            ids.append(nid); rows.append(r)
    store = VectorStore(ids, np.asarray(rows, dtype=np.float32).reshape(len(rows), embedder.dim))
    _STATE.stores[key] = _Loaded(hashes, store)
    return store, {"model": embedder.model_id, "notes": len(per_note), "vectors": len(ids),
                   "embedded": len(set(todo_ids)), "path": str(path)}


def build(root=None, allow_download: bool = True) -> dict:
    """Used by `brain index`: load (downloading if needed) the model and refresh the vector cache.
    Returns {"enabled": False, "reason": ...} instead of raising when semantic search is off."""
    emb = get_embedder(allow_download=allow_download)
    if emb is None:
        return {"enabled": False, "reason": status() or "unavailable", "hint": ENABLE_HINT}
    t0 = time.perf_counter()
    _, stats = ensure_vectors(emb, root)
    return {"enabled": True, **stats, "seconds": round(time.perf_counter() - t0, 2)}


def note_scores(query: str, root=None, best_questions: bool = False):
    """Cosine similarity of `query` to every note (max over each note's vectors), or None when the
    semantic layer is unavailable. Builds missing/stale vectors lazily. With best_questions=True
    returns (scores, {note_id: index of its closest `questions` entry, or None}) instead."""
    emb = get_embedder()
    if emb is None:
        return None
    store, _ = ensure_vectors(emb, root)
    import numpy as np
    res = store.note_scores_best(np.asarray(emb.embed_query(query), dtype=np.float32))
    return res if best_questions else res[0]


# ---------------------------------------------------------------- model files

def _hf_repo(model_id: str) -> str | None:
    """Hugging Face repo FastEmbed downloads `model_id` from (embedding models and rerankers)."""
    try:
        from fastembed import TextEmbedding
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError:
        return None
    for m in [*TextEmbedding.list_supported_models(), *TextCrossEncoder.list_supported_models()]:
        if m["model"].lower() == model_id.lower():
            return (m.get("sources") or {}).get("hf")
    return None


def model_disk_mb(model_id: str) -> float | None:
    """On-disk size of one downloaded model (its cache folder plus shared blobs it links to)."""
    repo = _hf_repo(model_id)
    d = model_dir() / ("models--" + repo.replace("/", "--")) if repo else None
    if d is None or not d.exists():
        return None
    files = {f.resolve() for f in d.rglob("*") if f.is_file()}
    return round(sum(f.stat().st_size for f in files) / 1e6, 1)


def prune_models(keep: Sequence[str] | None = None, dry_run: bool = False) -> dict:
    """Delete downloaded models in model_dir() other than `keep` (default: the configured embedding
    model, plus the configured reranker when ALEXAI_RERANK is on).
    The Hugging Face cache may store large files in a shared top-level blobs/ folder, so a blob is
    removed only when no kept model links to it. Returns {kept, removed, freed_mb, size_mb}."""
    import shutil
    base = model_dir()
    if not keep:
        from . import rerank
        keep = [configured_model()] + ([rerank.configured_model()] if rerank.enabled() else [])
    keep = list(keep)
    keep_dirs = {"models--" + r.replace("/", "--") for r in (_hf_repo(m) for m in keep) if r}
    if not base.exists():
        return {"kept": sorted(keep_dirs), "removed": [], "freed_mb": 0.0, "size_mb": 0.0}
    if not keep_dirs:
        raise AlexAIError(f"cannot map {keep} to downloaded model folders; nothing removed")

    def size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())

    before = size(base)
    removed = sorted(d.name for d in base.glob("models--*") if d.is_dir() and d.name not in keep_dirs)
    used = {f.resolve() for d in keep_dirs if (base / d).exists() for f in (base / d).rglob("*") if f.is_symlink()}
    orphan_blobs = [f for f in (base / "blobs").rglob("*") if f.is_file() and f.resolve() not in used] \
        if (base / "blobs").exists() else []
    if not dry_run:
        for name in removed:
            shutil.rmtree(base / name)
        for f in orphan_blobs:
            f.unlink()
        shutil.rmtree(base / ".locks", ignore_errors=True)
    after = before - sum(f.stat().st_size for f in orphan_blobs) - sum(size(base / n) for n in removed) \
        if dry_run else size(base)
    return {"kept": sorted(keep_dirs), "removed": removed, "freed_mb": round((before - after) / 1e6, 1),
            "size_mb": round(after / 1e6, 1), "dry_run": dry_run}
