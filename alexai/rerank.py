"""Optional second-stage reranker: a local cross-encoder rescores the top fused candidates.

Off by default. Measured on the dev eval sets it moved recall@8 by +0 to +4 expected notes out of
130 (bootstrap 95% intervals include zero) and MRR by about +0.03, which is within noise, so it is
not worth a second model load on every search. Turn it on with ALEXAI_RERANK=on, then run
`brain index` once to download the model (search never downloads).

Everything model-specific sits behind the small `Reranker` interface (model_id, score(query, texts)).
The default backend runs an ONNX cross-encoder through FastEmbed (no PyTorch); tests inject a fake
with `set_reranker`. The reranker does not replace the fused ranking: its rank is blended with the
fused rank (reciprocal-rank style), so a single odd cross-encoder score cannot bury a strong hit."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .semantic import model_dir
from .util import AlexAIError

DEFAULT_MODEL = "BAAI/bge-reranker-base"  # best of the three measured; ~1.1 GB on disk
DEFAULT_ON = False
DEPTH = 20          # fused candidates the cross-encoder rescores
BLEND_WEIGHT = 0.5  # weight of the cross-encoder rank relative to the fused rank
BLEND_K = 60        # rank-blend constant (as in reciprocal rank fusion)
ENABLE_HINT = "set ALEXAI_RERANK=on and run `brain index` to download the reranker"


class RerankUnavailable(AlexAIError):
    """Raised when the reranker cannot run (extra not installed, model not downloaded)."""


class Reranker(Protocol):
    model_id: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...  # higher = more relevant


def configured_model() -> str:
    return os.environ.get("ALEXAI_RERANK_MODEL") or DEFAULT_MODEL


def enabled() -> bool:
    """ALEXAI_RERANK=on|off overrides DEFAULT_ON."""
    v = os.environ.get("ALEXAI_RERANK", "").strip().lower()
    if v in {"1", "on", "true", "yes"}:
        return True
    if v in {"0", "off", "false", "no"}:
        return False
    return DEFAULT_ON


class FastEmbedReranker:
    """Local ONNX cross-encoder via FastEmbed's TextCrossEncoder."""

    def __init__(self, model_id: str | None = None, allow_download: bool = False, threads: int | None = None):
        self.model_id = model_id or configured_model()
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise RerankUnavailable(f"the semantic extra is not installed ({exc.name})") from exc
        if not allow_download:
            try:
                from loguru import logger
                logger.disable("fastembed")
            except ImportError:
                pass
        t0 = time.perf_counter()
        try:
            self._model = TextCrossEncoder(self.model_id, cache_dir=str(model_dir()), threads=threads,
                                           local_files_only=not allow_download)
        except Exception as exc:  # noqa: BLE001 - any failure means "reranker off"
            hint = "run `brain index` with ALEXAI_RERANK=on to download it" if not allow_download \
                else f"{type(exc).__name__}: {exc}"
            raise RerankUnavailable(f"reranker {self.model_id} is not available ({hint})") from exc
        self.load_sec = time.perf_counter() - t0

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, list(texts), batch_size=32)] if texts else []


# ---------------------------------------------------------------- process-level backend

@dataclass
class _State:
    reranker: Reranker | None = None
    error: str | None = None
    injected: bool = False


_STATE = _State()


def set_reranker(reranker: Reranker | None, reason: str = "reranker disabled") -> None:
    """Inject a backend (tests, servers). None turns reranking off regardless of ALEXAI_RERANK."""
    _STATE.reranker, _STATE.injected = reranker, True
    _STATE.error = None if reranker is not None else reason


def reset() -> None:
    _STATE.reranker, _STATE.error, _STATE.injected = None, None, False


def get_reranker(allow_download: bool = False) -> Reranker | None:
    """The process-wide reranker, loaded once; None (with `status()` saying why) when off."""
    if _STATE.injected:
        return _STATE.reranker
    if not enabled():
        _STATE.error = "reranker off (ALEXAI_RERANK)"
        return None
    want = configured_model()
    if _STATE.reranker is not None and _STATE.reranker.model_id == want:
        return _STATE.reranker
    if _STATE.error is not None and not allow_download and not _STATE.error.startswith("reranker off"):
        return None  # already failed this process
    try:
        _STATE.reranker, _STATE.error = FastEmbedReranker(want, allow_download=allow_download), None
    except RerankUnavailable as exc:
        _STATE.reranker, _STATE.error = None, str(exc)
    return _STATE.reranker


def status() -> str | None:
    return _STATE.error


def build(allow_download: bool = True) -> dict:
    """Used by `brain index`: load (downloading if needed) the reranker when it is enabled."""
    r = get_reranker(allow_download=allow_download)
    if r is None:
        return {"enabled": False, "reason": status() or "unavailable", "hint": ENABLE_HINT}
    return {"enabled": True, "model": r.model_id}


# ---------------------------------------------------------------- what the reranker sees

def note_text(doc: dict, best_question: str | None) -> str:
    """Title (with aliases), the note's first line, and the note question closest to the query.
    Measured against title+summary, title+summary+all questions, and title+body: the full body was
    both slower and worse (cross-encoders trained on short passages), the bare summary too thin."""
    head = str(doc.get("title") or "")
    aliases = [str(a) for a in doc.get("aliases") or []]
    if aliases:
        head += f" (also called: {', '.join(aliases)})"
    parts = [head + ".", str(doc.get("summary") or "")]
    if best_question:
        parts.append(best_question)
    return " ".join(p for p in parts if p)


def blend(order: list[str], ce_scores: dict[str, float], depth: int | None = None, weight: float | None = None,
          k: int | None = None) -> dict[str, float]:
    """Blend the fused order with the cross-encoder order over the first `depth` ids:
    score = 1/(k + fused rank) + weight/(k + reranker rank). Ids beyond `depth` keep 1/(k + fused rank),
    which is always below every reranked id, so the reranker only reorders the head of the list.
    Defaults: DEPTH, BLEND_WEIGHT, BLEND_K."""
    depth = DEPTH if depth is None else depth
    weight = BLEND_WEIGHT if weight is None else weight
    k = BLEND_K if k is None else k
    head = order[:depth]
    ce_rank = {i: n for n, i in enumerate(sorted(head, key=lambda i: (-ce_scores.get(i, float("-inf")), i)), 1)}
    out = {i: 1.0 / (k + n) + weight / (k + ce_rank[i]) for n, i in enumerate(head, 1)}
    for n, i in enumerate(order[depth:], depth + 1):
        out[i] = 1.0 / (k + n)
    return out
