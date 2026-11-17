"""Evaluation helpers. `retrieval` measures recall@k and MRR of `search_brain` against the
`expect_notes` lists in evals/questions.yaml (recall is also broken down by an optional
per-question `style` key), plus three looser views of the same ranked lists:
- lenient: an expected note also counts as found when one of the question's optional
  `accept_notes` (other notes that would answer it acceptably) is in the top k;
- reachable: an expected note also counts when it is in `related` of one of the top
  REACHABLE_FROM results (the agent is told to follow related links);
- solved: share of questions with at least one expected note in the top k."""
from __future__ import annotations

from pathlib import Path

import yaml

from . import brain
from .paths import resolve_root
from .util import AlexAIError

DEFAULT_QUESTIONS = Path("evals") / "questions.yaml"
REACHABLE_FROM = 3  # reachable@k follows `related` links of this many top results


def load_questions(path: str | Path | None = None, root=None) -> list[dict]:
    p = Path(path) if path else resolve_root(root) / DEFAULT_QUESTIONS
    if not p.exists():
        raise AlexAIError(f"questions file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        raise AlexAIError(f"cannot parse {p}: {exc}") from exc
    if not isinstance(data, list):
        raise AlexAIError(f"{p} must be a YAML list of questions")
    return data


def _rr(expected: list[str], retrieved: list[str]) -> float:
    """Reciprocal rank of the first expected note in the retrieved list (0 if none)."""
    ranks = [retrieved.index(e) + 1 for e in expected if e in retrieved]
    return 1.0 / min(ranks) if ranks else 0.0


def retrieval(k: int = 8, questions: str | Path | None = None, root=None, mode: str | None = None) -> dict:
    """Run every question with non-empty expect_notes through search_brain.
    Returns {k, recall, hits, expected, mrr, by_style, lenient_hits, reachable_hits, solved,
    style_extras, questions:[{id, question, style, expected, hits, misses, recall, rr, retrieved,
    accept, lenient_hits, reachable_hits}]}. `by_style` maps each `style` value to {questions, hits,
    expected, recall, mrr}; `style_extras` maps it to {questions, solved, lenient_hits,
    reachable_hits}; both are empty when no question carries a style."""
    related = {d["id"]: list(d.get("related") or []) for d in brain._load_index(root)["notes"]}
    rows, hits_total, expected_total = [], 0, 0
    for q in load_questions(questions, root):
        expected = list(q.get("expect_notes") or [])
        if not expected:
            continue
        accept = list(q.get("accept_notes") or [])
        retrieved = [r["id"] for r in brain.search_brain(q["question"], k=k, root=root, mode=mode)]
        hits = [e for e in expected if e in retrieved]
        misses = [e for e in expected if e not in retrieved]
        accepted = any(a in retrieved for a in accept)
        linked = {r_ for i in retrieved[:REACHABLE_FROM] for r_ in related.get(i, ())}
        hits_total += len(hits)
        expected_total += len(expected)
        rows.append({"id": q.get("id"), "question": q["question"], "style": q.get("style"),
                     "expected": expected, "hits": hits, "misses": misses,
                     "recall": round(len(hits) / len(expected), 4), "rr": round(_rr(expected, retrieved), 4),
                     "retrieved": retrieved, "accept": accept,
                     "lenient_hits": len(expected) if accepted else len(hits),
                     "reachable_hits": len([e for e in expected if e in retrieved or e in linked])})
    recall = round(hits_total / expected_total, 4) if expected_total else 0.0
    mrr = round(sum(r["rr"] for r in rows) / len(rows), 4) if rows else 0.0
    by_style: dict[str, dict] = {}
    extras: dict[str, dict] = {}
    for r in rows:
        if r["style"] is None:
            continue
        g = by_style.setdefault(str(r["style"]), {"questions": 0, "hits": 0, "expected": 0, "rr_sum": 0.0})
        g["questions"] += 1
        g["hits"] += len(r["hits"])
        g["expected"] += len(r["expected"])
        g["rr_sum"] += r["rr"]
        x = extras.setdefault(str(r["style"]), {"questions": 0, "solved": 0, "lenient_hits": 0, "reachable_hits": 0})
        x["questions"] += 1
        x["solved"] += bool(r["hits"])
        x["lenient_hits"] += r["lenient_hits"]
        x["reachable_hits"] += r["reachable_hits"]
    for g in by_style.values():
        g["recall"] = round(g["hits"] / g["expected"], 4) if g["expected"] else 0.0
        g["mrr"] = round(g.pop("rr_sum") / g["questions"], 4)
    return {"k": k, "mode": mode or "default", "recall": recall, "hits": hits_total, "expected": expected_total, "mrr": mrr,
            "by_style": dict(sorted(by_style.items())),
            "lenient_hits": sum(r["lenient_hits"] for r in rows),
            "reachable_hits": sum(r["reachable_hits"] for r in rows),
            "solved": sum(bool(r["hits"]) for r in rows),
            "style_extras": dict(sorted(extras.items())), "questions": rows}


def format_retrieval(res: dict) -> str:
    lines = []
    for r in res["questions"]:
        lines.append(f"{len(r['hits'])}/{len(r['expected'])}  {r['id']}: {r['question']}")
        for h in r["hits"]:
            lines.append(f"      hit   {h} (rank {r['retrieved'].index(h) + 1})")
        for m in r["misses"]:
            lines.append(f"      MISS  {m}")
    lines.append(f"mode: {res.get('mode', 'default')}")
    lines.append(f"recall@{res['k']}: {res['hits']}/{res['expected']} = {res['recall']:.1%} "
                 f"over {len(res['questions'])} questions")
    lines.append(f"MRR@{res['k']}: {res['mrr']:.3f}")
    for style, g in (res.get("by_style") or {}).items():
        lines.append(f"  style {style}: recall {g['hits']}/{g['expected']} = {g['recall']:.1%}, "
                     f"MRR {g['mrr']:.3f} over {g['questions']} questions")
    if "solved" in res:
        n, e, k = len(res["questions"]), res["expected"], res["k"]
        pct = lambda a, b: f"{round(a / b, 4):.1%}" if b else "n/a"  # noqa: E731
        lines.append(f"lenient recall@{k} (expected or an accept_note in top {k}): "
                     f"{res['lenient_hits']}/{e} = {pct(res['lenient_hits'], e)}")
        lines.append(f"reachable@{k} (in top {k} or linked from the top {REACHABLE_FROM}): "
                     f"{res['reachable_hits']}/{e} = {pct(res['reachable_hits'], e)}")
        lines.append(f"questions solved@{k} (at least one expected note in top {k}): "
                     f"{res['solved']}/{n} = {pct(res['solved'], n)}")
        for style, x in (res.get("style_extras") or {}).items():
            lines.append(f"  style {style}: solved {x['solved']}/{x['questions']}, "
                         f"lenient {x['lenient_hits']}, reachable {x['reachable_hits']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- embedding-model bake-off

def _at(res: dict, k: int) -> dict:
    """recall@k / hits@k for a retrieval result computed with a larger k (lists are prefixes)."""
    hits = sum(len([e for e in r["expected"] if e in r["retrieved"][:k]]) for r in res["questions"])
    by_style: dict[str, list[int]] = {}
    for r in res["questions"]:
        g = by_style.setdefault(str(r["style"]), [0, 0])
        g[0] += len([e for e in r["expected"] if e in r["retrieved"][:k]])
        g[1] += len(r["expected"])
    return {"hits": hits, "expected": res["expected"], "by_style": by_style}


def _summary(res: dict) -> dict:
    a5, a8 = _at(res, 5), _at(res, 8)
    return {"r5": a5["hits"], "r8": a8["hits"], "expected": res["expected"], "mrr": res["mrr"],
            "by_style_r8": {s: f"{h}/{n}" for s, (h, n) in sorted(a8["by_style"].items()) if s != "None"}}


def bakeoff(models: list[str], questions: list, modes=("semantic", "hybrid"), root=None, log=None) -> dict:
    """Score each embedding model the same way: fixed note-text recipe and fusion, retrieval at k=8
    (recall@5 is read from the same lists), plus download size, model load time, cold / warm query
    embedding latency and the time to embed every note. A lexical baseline row is included."""
    import statistics
    import time

    from . import semantic
    from .util import parse_frontmatter

    log = log or (lambda msg: None)
    lay = brain.layout(root)
    texts = []
    for p in sorted(lay.notes.glob("*.md")):
        try:
            meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        except AlexAIError:
            continue
        texts += semantic.note_texts(meta, body)
    qtexts = [q["question"] for qf in questions for q in load_questions(qf, root) if q.get("expect_notes")]

    out = {"recipe": semantic.RECIPE, "fusion_weight": brain.FUSION_LEXICAL_WEIGHT, "notes_texts": len(texts),
           "questions": [str(q or DEFAULT_QUESTIONS) for q in questions], "models": []}
    semantic.set_embedder(None, reason="bake-off lexical baseline")
    out["lexical"] = [_summary(retrieval(k=8, questions=qf, root=root, mode="lexical")) for qf in questions]
    try:
        for model in models:
            log(f"[bakeoff] {model}: loading (downloads on first use)")
            semantic.FastEmbedBackend(model, allow_download=True)  # ensure it is on disk
            size_mb = semantic.model_disk_mb(model)
            emb = semantic.FastEmbedBackend(model)  # timed load from local files only
            t0 = time.perf_counter(); emb.embed_query(qtexts[0]); cold_ms = (time.perf_counter() - t0) * 1e3
            warm = []
            for q in qtexts[1:41]:
                t0 = time.perf_counter(); emb.embed_query(q); warm.append((time.perf_counter() - t0) * 1e3)
            log(f"[bakeoff] {model}: embedding {len(texts)} note texts")
            t0 = time.perf_counter(); emb.embed_documents(texts); embed_all = time.perf_counter() - t0
            semantic.set_embedder(emb)
            row = {"model": model, "dim": emb.dim, "download_mb": size_mb, "load_sec": round(emb.load_sec, 2),
                   "cold_query_ms": round(cold_ms, 1), "warm_query_ms": round(statistics.median(warm), 1),
                   "embed_all_sec": round(embed_all, 1), "results": []}
            for qf in questions:
                row["results"].append({m: _summary(retrieval(k=8, questions=qf, root=root, mode=m)) for m in modes})
            out["models"].append(row)
            del emb
    finally:
        semantic.reset()
    return out


def format_bakeoff(res: dict) -> str:
    lines = [f"recipe {res['recipe']}, fusion lexical weight {res['fusion_weight']}, "
             f"{res['notes_texts']} note texts embedded per model", ""]
    lines.append(f"{'model':48} {'dim':>4} {'MB':>6} {'load s':>6} {'cold ms':>7} {'warm ms':>7} {'embed s':>7}")
    for m in res["models"]:
        lines.append(f"{m['model']:48} {m['dim']:>4} {m['download_mb']:>6} {m['load_sec']:>6} "
                     f"{m['cold_query_ms']:>7} {m['warm_query_ms']:>7} {m['embed_all_sec']:>7}")
    for i, qf in enumerate(res["questions"]):
        lines += ["", f"== {qf}  (retrieval at k=8; recall@5 read from the same ranked lists)"]
        lines.append(f"{'model':48} {'mode':9} {'R@5':>7} {'R@8':>7} {'MRR':>6}  R@8 by style")
        def row(name, mode, s):
            n = s["expected"]
            styles = ", ".join(f"{k} {v}" for k, v in s["by_style_r8"].items())
            lines.append(f"{name:48} {mode:9} {s['r5']:>3}/{n:<3} {s['r8']:>3}/{n:<3} {s['mrr']:>6.3f}  {styles}")
        row("(lexical baseline)", "lexical", res["lexical"][i])
        for m in res["models"]:
            for mode, s in m["results"][i].items():
                row(m["model"], mode, s)
    return "\n".join(lines)
