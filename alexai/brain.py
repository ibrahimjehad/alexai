"""The brain: atomic notes + source records. Read, validate, index and search.

Search is a stdlib BM25 over title / aliases / topics / questions / summary / body using
brain/index.json, optionally fused with meaning-based (embedding) search from alexai.semantic.
Everything goes through `search_brain`, so backends can change without changing callers."""
from __future__ import annotations

import datetime as _dt
import json
import math
import re
from collections import Counter
from pathlib import Path

import yaml

from . import manifest
from .paths import layout
from .schema import NOTE_OPTIONAL, NOTE_TYPES, note_meta_warnings, validate_note_meta, validate_source_meta
from .util import AlexAIError, atomic_write_json, atomic_write_text, is_kebab, now_iso, parse_frontmatter, read_json

INDEX_VERSION = 3  # 2: stemmed tokens + summary field; 3: questions + aliases fields
# aliases are alternative names (as strong as the title); questions are several plain-language
# phrasings whose terms often repeat across items, so they sit at topic level.
FIELD_WEIGHTS = {"title": 4, "aliases": 4, "topics": 3, "questions": 3, "summary": 2, "body": 1}
# Fields excluded from BM25 document length so enriched notes are not penalised for carrying them.
ENRICHMENT_FIELDS = ("aliases", "questions")
BM25_K1, BM25_B = 1.2, 0.75
TYPE_BOOST = {"framework": 1.15, "definition": 1.1}
RELATED_SEED_HITS = 5        # top hits whose `related` notes are pulled in
RELATED_DISCOUNT = 0.35      # linked note gains this fraction of its best parent's score
SYNONYM_WEIGHT = 0.5         # expansion terms count half as much as the user's own words
SYNONYMS_FILE = "synonyms.yaml"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i if in into is it its of on or that the "
    "their there this to was what when where which who why will with you your do does can we our "
    "my me im ive am should would could shall may might must some any about so than then them they "
    "us just also very really want need help please tell give get got make made".split()
)
_VOWELS = set("aeiouy")


def stem(tok: str) -> str:
    """Light, deterministic suffix stripper (Porter-flavoured, far simpler). It only has to map
    query and note words onto the same key: refer/referral/referrals -> refer, valuable/value -> valu."""
    if tok.isdigit() or len(tok) < 3:
        return tok
    if len(tok) == 3:  # ads -> ad; leave other short words alone
        return tok[:-1] if tok.endswith("s") and tok[1] not in "su" else tok
    if tok.endswith("ies") and len(tok) > 4:
        tok = tok[:-3] + "y"
    elif tok.endswith("sses"):
        tok = tok[:-2]
    elif tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        tok = tok[:-1]
    for suf, min_stem in (("ing", 3), ("ed", 3), ("ment", 4), ("ness", 4), ("able", 3), ("ible", 3),
                          ("ally", 3), ("ly", 4), ("al", 4)):
        if tok.endswith(suf) and len(tok) - len(suf) >= min_stem and _VOWELS & set(tok[: -len(suf)]):
            tok = tok[: -len(suf)]
            break
    if len(tok) >= 4 and tok.endswith("e"):  # name/naming -> nam, price/pricing -> pric
        tok = tok[:-1]
    if len(tok) > 3 and tok[-1] == tok[-2] and tok[-1] not in "lsz" and tok[-1] not in _VOWELS:
        tok = tok[:-1]  # referr -> refer, runn -> run
    return tok


def tokenize(text: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        tok = tok.replace("'", "")
        if tok in STOPWORDS or len(tok) < 2:
            continue
        out.append(stem(tok))
    return out


def load_synonyms(root=None) -> dict[str, list[str]]:
    """brain/synonyms.yaml maps a word to phrases it should also match: {word: [phrase, ...]}.
    Keys and phrases are tokenized/stemmed, so plural or tense variants need no entry."""
    path = layout(root).brain / SYNONYMS_FILE
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AlexAIError(f"cannot parse {path}: {exc}") from exc
    out: dict[str, list[str]] = {}
    for key, phrases in raw.items():
        if isinstance(phrases, str):
            phrases = [phrases]
        for k in tokenize(str(key)):
            out.setdefault(k, []).extend(t for ph in phrases or [] for t in tokenize(str(ph)))
    return out


def _query_terms(query: str, root=None) -> dict[str, float]:
    """Stemmed query terms with weights: user words 1.0, synonym expansions SYNONYM_WEIGHT."""
    terms: dict[str, float] = {}
    for t in tokenize(query):
        terms[t] = 1.0
    syn = load_synonyms(root)
    for t in list(terms):
        for e in syn.get(t, ()):
            terms[e] = max(terms.get(e, 0.0), SYNONYM_WEIGHT)
    return terms


# ---------------------------------------------------------------- reading

def _note_path(note_id: str, root=None) -> Path:
    if not is_kebab(note_id):
        raise AlexAIError(f"invalid note id {note_id!r}")
    return layout(root).notes / f"{note_id}.md"


def _jsonable(meta: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, _dt.date) else v) for k, v in meta.items()}


def get_note(note_id: str, root=None) -> dict:
    path = _note_path(note_id, root)
    if not path.exists():
        raise AlexAIError(f"note {note_id!r} not found")
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return {**_jsonable(meta), **{k: list(meta.get(k) or []) for k in NOTE_OPTIONAL},
            "body": body, "path": str(path.relative_to(layout(root).root))}


def get_source_record(source_id: str, root=None) -> dict:
    if not is_kebab(source_id):
        raise AlexAIError(f"invalid source id {source_id!r}")
    path = layout(root).sources / f"{source_id}.md"
    if not path.exists():
        raise AlexAIError(f"source record {source_id!r} not found")
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return {**_jsonable(meta), "body": body}


def _iter_md(folder: Path):
    if folder.exists():
        yield from sorted(p for p in folder.glob("*.md") if not p.name.startswith("."))


def list_notes(topics: list[str] | None = None, type: str | None = None, root=None) -> list[dict]:
    out = []
    for path in _iter_md(layout(root).notes):
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except AlexAIError:
            continue
        if type and meta.get("type") != type:
            continue
        if topics and not set(topics) & set(meta.get("topics") or []):
            continue
        out.append({k: _jsonable(meta).get(k) for k in ("id", "type", "title", "topics", "updated")}
                   | {k: list(meta.get(k) or []) for k in NOTE_OPTIONAL})
    return out


# ---------------------------------------------------------------- validation

def validate(root=None) -> dict:
    """Validate every note and source record plus cross references. Returns
    {ok, errors:[{file, error}], warnings:[...], counts}."""
    lay = layout(root)
    errors, warnings = [], []
    notes, sources = {}, {}
    known_sources = {e["id"] for e in manifest.all_entries(root)}

    for path in _iter_md(lay.notes):
        rel = str(path.relative_to(lay.root))
        try:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except AlexAIError as exc:
            errors.append({"file": rel, "error": str(exc)})
            continue
        for e in validate_note_meta(meta, path.stem):
            errors.append({"file": rel, "error": e})
        if not body.strip():
            errors.append({"file": rel, "error": "empty body"})
        for w in note_meta_warnings(meta):
            warnings.append({"file": rel, "warning": w})
        notes[path.stem] = meta

    for path in _iter_md(lay.sources):
        rel = str(path.relative_to(lay.root))
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except AlexAIError as exc:
            errors.append({"file": rel, "error": str(exc)})
            continue
        for e in validate_source_meta(meta, path.stem):
            errors.append({"file": rel, "error": e})
        if path.stem not in known_sources:
            errors.append({"file": rel, "error": f"source {path.stem!r} is not registered in manifest.json"})
        sources[path.stem] = meta

    for nid, meta in notes.items():
        rel = f"brain/notes/{nid}.md"
        for s in meta.get("sources") or []:
            if isinstance(s, dict) and s.get("id") not in known_sources:
                errors.append({"file": rel, "error": f"cites unknown source {s.get('id')!r}"})
        for r in meta.get("related") or []:
            if r not in notes:
                errors.append({"file": rel, "error": f"related note {r!r} does not exist"})
            elif r == nid:
                errors.append({"file": rel, "error": "note relates to itself"})
    for sid, meta in sources.items():
        rel = f"brain/sources/{sid}.md"
        for n in meta.get("notes") or []:
            if n not in notes:
                errors.append({"file": rel, "error": f"lists missing note {n!r}"})
    # back-references: every note citing a source should be listed by that source record
    for nid, meta in notes.items():
        for s in meta.get("sources") or []:
            sid = s.get("id") if isinstance(s, dict) else None
            if sid in sources and nid not in (sources[sid].get("notes") or []):
                warnings.append({"file": f"brain/sources/{sid}.md", "warning": f"does not list note {nid!r}"})

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"notes": len(notes), "sources": len(sources)}}


# ---------------------------------------------------------------- index

def build_index(root=None, semantic: bool = True) -> dict:
    """Write brain/index.json (search data) and brain/index.md (human/agent overview), and, when
    `semantic` is true, refresh the note-vector cache (downloading the model if needed) and, if the
    optional reranker is switched on (ALEXAI_RERANK=on), make sure its model is downloaded. The
    result's "semantic" / "rerank" entries say whether each is on, and why not when it is off."""
    lay = layout(root)
    docs, df = [], Counter()
    for path in _iter_md(lay.notes):
        try:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except AlexAIError:
            continue
        if validate_note_meta(meta, path.stem):
            continue  # invalid notes are excluded; run `brain validate`
        tf: Counter = Counter()
        length = 0
        summary = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")), "")
        questions, aliases = list(meta.get("questions") or []), list(meta.get("aliases") or [])
        fields = {"title": meta["title"], "topics": " ".join(meta["topics"]).replace("-", " "),
                  "summary": summary, "body": body, "questions": "\n".join(questions),
                  "aliases": "\n".join(aliases)}
        for field, text in fields.items():
            for tok in tokenize(text):
                tf[tok] += FIELD_WEIGHTS[field]
                if field not in ENRICHMENT_FIELDS:
                    length += FIELD_WEIGHTS[field]
        df.update(tf.keys())
        docs.append({
            **{k: _jsonable(meta)[k] for k in ("id", "type", "title", "topics", "sources", "related", "updated")},
            "questions": questions, "aliases": aliases,
            "summary": summary[:240], "length": length, "tf": dict(tf),
        })
    avgdl = (sum(d["length"] for d in docs) / len(docs)) if docs else 0.0
    index = {"version": INDEX_VERSION, "built": now_iso(), "n_docs": len(docs), "avgdl": avgdl,
             "df": dict(df), "notes": docs}
    # Keep the old timestamp when nothing else changed, so re-indexing a fresh clone leaves git clean.
    try:
        prev = read_json(lay.index_json)
    except Exception:
        prev = None
    if isinstance(prev, dict) and {**prev, "built": None} == json.loads(json.dumps({**index, "built": None})):
        index["built"] = prev.get("built", index["built"])
    atomic_write_json(lay.index_json, index)
    atomic_write_text(lay.index_md, _render_index_md(docs))
    out = {"notes": len(docs), "index_json": str(lay.index_json), "index_md": str(lay.index_md)}
    if semantic:
        from . import rerank as _rerank
        from . import semantic as _semantic
        out["semantic"] = _semantic.build(root, allow_download=True)
        out["rerank"] = _rerank.build(allow_download=True)  # downloads only when ALEXAI_RERANK=on
    return out


def _render_index_md(docs: list[dict]) -> str:
    lines = ["# Brain index", "", "_Generated by `python -m alexai brain index`. Do not edit by hand._", ""]
    if not docs:
        lines.append("No notes yet. Use the feed skill to distill sources into notes.")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(docs)} notes.")
    for t in NOTE_TYPES:
        group = sorted((d for d in docs if d["type"] == t), key=lambda d: d["title"].lower())
        if not group:
            continue
        lines += ["", f"## {t.capitalize()}s", ""]
        for d in group:
            lines.append(f"- **{d['title']}** (`{d['id']}`) [{', '.join(d['topics'])}] {d['summary'][:140]}")
    topics = Counter(t for d in docs for t in d["topics"])
    lines += ["", "## Topics", "", ", ".join(f"{t} ({n})" for t, n in sorted(topics.items()))]
    return "\n".join(lines) + "\n"


def _load_index(root=None) -> dict:
    lay = layout(root)
    idx = read_json(lay.index_json)
    if idx is None or idx.get("version") != INDEX_VERSION:
        build_index(root, semantic=False)  # search never downloads; vectors are built lazily
        idx = read_json(lay.index_json)
    return idx


# ---------------------------------------------------------------- search

SEARCH_MODES = ("hybrid", "lexical", "semantic")
RRF_K = 60  # reciprocal rank fusion constant (Cormack et al. 2009); kept for comparison, not the default
# Hybrid fusion (chosen on evals/retrieval_holdout.yaml + evals/questions.yaml; see README):
# each ranker's scores are z-normalised over the allowed notes and mixed linearly, so a note far
# above the rest in one ranker keeps that margin instead of being flattened to a rank.
FUSION_LEXICAL_WEIGHT = 0.4  # semantic gets 1 - this; recall is flat for 0.3-0.5
FUSION_KEEP_TOP = 1          # each ranker's top-N notes are always kept inside the returned top k


def _lexical_scores(idx: dict, terms: dict[str, float], allowed) -> dict[str, float]:
    """BM25 score per allowed note (no related expansion). With no terms every allowed note scores 0."""
    n, avgdl, df = idx["n_docs"], idx["avgdl"] or 1.0, idx["df"]
    scores: dict[str, float] = {}
    for d in idx["notes"]:
        if not allowed(d):
            continue
        score = 0.0
        for t, w in terms.items():
            f = d["tf"].get(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += w * idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * d["length"] / avgdl))
        if terms and score <= 0:
            continue
        scores[d["id"]] = score * TYPE_BOOST.get(d["type"], 1.0)
    return scores


def _add_related(scores: dict[str, float], by_id: dict, allowed) -> dict[str, float]:
    """Notes linked via `related` from the top hits gain a discounted share of their parent's score."""
    seeds = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:RELATED_SEED_HITS]
    bonus: dict[str, float] = {}
    for sid, sscore in seeds:
        for rid in by_id[sid].get("related") or []:
            rd = by_id.get(rid)
            if rd is not None and rid != sid and allowed(rd):
                bonus[rid] = max(bonus.get(rid, 0.0), sscore * RELATED_DISCOUNT)
    out = dict(scores)
    for rid, b in bonus.items():
        out[rid] = out.get(rid, 0.0) + b
    return out


def _ranked(scores: dict[str, float]) -> list[str]:
    return [i for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def rrf(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal rank fusion: score(d) = sum over rankings of 1 / (k + rank of d), rank from 1."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (k + rank)
    return fused


def _zscores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
    return {i: ((v - mean) / sd if sd > 0 else 0.0) for i, v in scores.items()}


def fuse(lexical: dict[str, float], sem: dict[str, float], weight: float | None = None) -> dict[str, float]:
    """Score fusion of the two rankers: weight * z(lexical) + (1 - weight) * z(semantic).
    z-scores are taken over every note in `sem` (all allowed notes); a note with no lexical match
    has lexical score 0 before normalising. Notes missing from `sem` are ignored.
    weight defaults to FUSION_LEXICAL_WEIGHT."""
    weight = FUSION_LEXICAL_WEIGHT if weight is None else weight
    zl = _zscores({i: lexical.get(i, 0.0) for i in sem})
    zs = _zscores(sem)
    return {i: weight * zl[i] + (1 - weight) * zs[i] for i in sem}


def keep_top(order: list[str], protected: list[str], k: int) -> list[str]:
    """Make sure every id in `protected` is within the first k of `order` (when k allows): protected
    ids missing from the top k replace the lowest unprotected entries there, and the top k keeps the
    original relative order, so displayed scores stay monotonic. The rest follows unchanged."""
    protected = [p for p in dict.fromkeys(protected) if p in order][:k]
    top = order[:k]
    for p in protected:
        if p in top:
            continue
        for j in range(len(top) - 1, -1, -1):
            if top[j] not in protected:
                top[j] = p
                break
    pos = {i: n for n, i in enumerate(order)}
    top.sort(key=pos.__getitem__)
    chosen = set(top)
    return top + [i for i in order if i not in chosen]


def search_brain(query: str, k: int = 8, topics: list[str] | None = None, type: str | None = None,
                 root=None, mode: str | None = None) -> list[dict]:
    """Rank notes for `query`. Returns [{id, title, type, topics, sources, score, summary}].

    mode:
    - "lexical": BM25 over field-weighted term frequencies (title = aliases > topics = questions >
      summary line > body; aliases/questions do not count toward document length) with light
      stemming, optional synonym expansion from brain/synonyms.yaml, a small boost for framework /
      definition notes, and a second pass that pulls in notes linked via `related` from the top hits
      at a discounted score. Score = BM25.
    - "semantic": cosine similarity between the query embedding and each note's vectors (max over
      the note's vectors; see alexai.semantic). Score = cosine.
    - "hybrid": score fusion of the lexical scores (as above, related pass included) and the
      semantic scores: FUSION_LEXICAL_WEIGHT * z(lexical) + (1 - FUSION_LEXICAL_WEIGHT) * z(semantic),
      z-scores over the allowed notes (see `fuse`). Each ranker's top FUSION_KEEP_TOP notes are then
      guaranteed a place in the returned top k (see `keep_top`). When the optional reranker is on
      (alexai.rerank, ALEXAI_RERANK=on) it rescores the top rerank.DEPTH fused notes and its rank is
      blended with the fused rank before that guarantee. Score = fused z-score, or the blended
      rank score when reranked.
    Default (None): hybrid when the semantic layer is available, otherwise lexical. An explicit
    "hybrid" silently falls back to lexical too; an explicit "semantic" raises when it is off.
    Topic / type filters apply in every mode, including to related-link additions."""
    from . import semantic

    if type and type not in NOTE_TYPES:
        raise AlexAIError(f"type must be one of {NOTE_TYPES}")
    if mode is not None and mode not in SEARCH_MODES:
        raise AlexAIError(f"mode must be one of {SEARCH_MODES}")
    idx = _load_index(root)
    by_id = {d["id"]: d for d in idx["notes"]}

    def allowed(d):
        return not (type and d["type"] != type) and not (topics and not set(topics) & set(d["topics"]))

    sem, best_q = None, {}
    if mode != "lexical":
        res = semantic.note_scores(query, root, best_questions=True)
        if res is None:
            if mode == "semantic":
                raise AlexAIError(f"semantic search is off: {semantic.status()}; {semantic.ENABLE_HINT}")
            mode = "lexical"
        else:
            sem, best_q = res
            sem = {i: s for i, s in sem.items() if i in by_id and allowed(by_id[i])}
            mode = mode or "hybrid"

    if mode == "semantic":
        scores = sem
        order = _ranked(scores)
    else:
        terms = _query_terms(query, root)
        scores = _lexical_scores(idx, terms, allowed)
        if terms:
            scores = _add_related(scores, by_id, allowed)
        if mode != "hybrid":
            order = _ranked(scores)
        else:
            lexical = scores
            scores = fuse(lexical, sem)
            order = _ranked(scores)
            scores, order = _maybe_rerank(query, order, scores, by_id, best_q, terms)
            protected = _ranked(sem)[:FUSION_KEEP_TOP]
            if lexical and max(lexical.values()) > 0:
                protected = _ranked(lexical)[:FUSION_KEEP_TOP] + protected
            order = keep_top(order, protected, max(1, k))

    results = [{k_: by_id[i][k_] for k_ in ("id", "title", "type", "topics", "sources", "summary")}
               | {"score": round(scores[i], 4)} for i in order[: max(1, k)]]
    return results


def _best_question(questions: list[str], terms: dict[str, float]) -> str | None:
    """Fallback when no embedding says which question is closest: most query terms in common."""
    if not questions:
        return None
    return max(questions, key=lambda q: sum(terms.get(t, 0.0) for t in set(tokenize(q))))


def _maybe_rerank(query: str, order: list[str], scores: dict[str, float], by_id: dict,
                  best_q: dict, terms: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Apply the optional cross-encoder (alexai.rerank) to the head of the fused order."""
    from . import rerank
    rr = rerank.get_reranker()
    if rr is None or not order:
        return scores, order
    head = order[: rerank.DEPTH]
    texts = []
    for i in head:
        d = by_id[i]
        qs = [q for q in d.get("questions") or [] if str(q).strip()]
        n = best_q.get(i)
        bq = qs[n] if n is not None and n < len(qs) else _best_question(qs, terms)
        texts.append(rerank.note_text(d, bq))
    try:
        ce = dict(zip(head, rr.score(query, texts)))
    except Exception:  # noqa: BLE001 - a failing reranker must never break search
        return scores, order
    blended = rerank.blend(order, ce)
    return blended, _ranked(blended)
