"""Semantic / hybrid search with a deterministic fake embedder: no model, no network."""
import hashlib
import json

import numpy as np
import pytest

from alexai import brain, semantic
from alexai.util import AlexAIError

from conftest import write_note

# words in one group share a dimension, so they are "close in meaning" with no shared spelling
CONCEPTS = [("money", "cash", "revenue", "profit"), ("price", "expensive", "cost", "pricey"),
            ("customer", "client", "buyer", "shopper"), ("quit", "cancel", "churn", "leave")]


class FakeEmbedder:
    dim = 32

    def __init__(self, model_id="fake/concepts-v1"):
        self.model_id = model_id
        self.doc_calls: list[list[str]] = []
        self.query_calls = 0

    def _vec(self, text):
        v = np.zeros(self.dim, dtype=np.float32)
        for w in "".join(c if c.isalnum() else " " for c in text.lower()).split():
            for i, group in enumerate(CONCEPTS):
                if w in group:
                    v[i] += 1.0
                    break
            else:
                v[4 + int(hashlib.md5(w.encode()).hexdigest(), 16) % (self.dim - 4)] += 0.2
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts):
        self.doc_calls.append(list(texts))
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)

    def embed_query(self, text):
        self.query_calls += 1
        return self._vec(text)


@pytest.fixture
def fake():
    emb = FakeEmbedder()
    semantic.set_embedder(emb)
    return emb


def _brain(root):
    write_note(root, "offers-raise-prices", "Raise your prices", ["pricing"],
               "Charge more and pick buyers who value the outcome.", type_="tactic")
    write_note(root, "money-models-continuity", "Continuity offers", ["money-models"],
               "Members who quit early need an onboarding fix; reduce churn.", type_="framework",
               extra='questions:\n  - "Why do my members cancel?"\n')
    write_note(root, "leads-warm-outreach", "Warm Outreach", ["leads"],
               "Contact people you already know and ask who they know.", type_="tactic")
    brain.build_index(root)


# ---------------------------------------------------------------- fusion maths

def test_rrf_sums_reciprocal_ranks():
    fused = brain.rrf([["a", "b", "c"], ["b", "d"]], k=60)
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 63)
    assert fused["d"] == pytest.approx(1 / 62)
    assert max(fused, key=fused.get) == "b"  # agreed-on items beat a single first place
    assert brain.rrf([[], ["x"]], k=10) == {"x": pytest.approx(1 / 11)}


# ---------------------------------------------------------------- modes

def test_semantic_finds_note_with_no_shared_words(root, fake):
    _brain(root)
    q = "my clients say it is too pricey"
    assert brain.search_brain(q, mode="lexical", root=root) == []  # no word overlap at all
    sem = brain.search_brain(q, mode="semantic", root=root)
    assert sem[0]["id"] == "offers-raise-prices"
    assert -1.0 <= sem[0]["score"] <= 1.0
    hyb = brain.search_brain(q, root=root)  # default is hybrid when an embedder is available
    assert hyb[0]["id"] == "offers-raise-prices"
    assert set(hyb[0]) == {"id", "title", "type", "topics", "sources", "summary", "score"}


def test_hybrid_combines_lexical_and_semantic_hits(root, fake):
    _brain(root)
    # "outreach" matches the outreach note by word; "buyers who cancel" matches the continuity note
    # (its question says "cancel", its body says "quit"/"churn") - both must reach the top two
    hyb = [r["id"] for r in brain.search_brain("outreach for buyers who cancel", k=3, root=root)]
    assert set(hyb[:2]) == {"leads-warm-outreach", "money-models-continuity"}


def test_hybrid_scores_are_fused_zscores_of_both_rankers(root, fake):
    _brain(root)
    # hybrid = brain.fuse of exactly the lexical-mode scores (related pass included) and the semantic scores
    q = "warm outreach customers"
    lex = {r["id"]: r["score"] for r in brain.search_brain(q, k=10, mode="lexical", root=root)}
    sem = {r["id"]: r["score"] for r in brain.search_brain(q, k=10, mode="semantic", root=root)}
    expected = brain.fuse(lex, sem)
    got = {r["id"]: r["score"] for r in brain.search_brain(q, k=10, mode="hybrid", root=root)}
    assert got.keys() == expected.keys()
    assert all(got[i] == pytest.approx(expected[i], abs=1e-2) for i in got)  # inputs were rounded


def test_fuse_is_weighted_sum_of_zscores():
    lex = {"a": 9.0, "b": 1.0}                     # "c" has no lexical match -> lexical score 0
    sem = {"a": 0.2, "b": 0.8, "c": 0.5}
    fused = brain.fuse(lex, sem, weight=0.4)
    zl, zs = brain._zscores({"a": 9.0, "b": 1.0, "c": 0.0}), brain._zscores(sem)
    assert fused == {i: pytest.approx(0.4 * zl[i] + 0.6 * zs[i]) for i in sem}
    assert brain._ranked(brain.fuse(lex, sem, weight=0.0)) == ["b", "c", "a"]
    assert brain._ranked(brain.fuse(lex, sem, weight=1.0))[0] == "a"
    assert brain.fuse({}, {"x": 0.3}) == {"x": 0.0}               # constant inputs -> z = 0, no crash
    assert brain.fuse({"zzz": 5.0}, {}) == {}                     # only allowed (semantic) notes are scored


def test_keep_top_guarantees_protected_ids():
    order = list("abcdefgh")
    assert brain.keep_top(order, ["g"], 3) == ["a", "b", "g", "c", "d", "e", "f", "h"]
    assert brain.keep_top(order, ["b", "h"], 3) == ["a", "b", "h", "c", "d", "e", "f", "g"]
    assert brain.keep_top(order, ["a"], 3) == order                # already inside: unchanged
    assert brain.keep_top(order, ["f", "g"], 1) == ["f"] + [i for i in order if i != "f"]  # k caps it
    assert brain.keep_top(order, ["missing"], 3) == order


def test_hybrid_never_buries_either_rankers_top_hit(root, fake, monkeypatch):
    _brain(root)
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    brain.build_index(root)
    q = "scarcity for clients who say it is pricey"
    lex_top = brain.search_brain(q, k=1, mode="lexical", root=root)[0]["id"]
    sem_top = brain.search_brain(q, k=1, mode="semantic", root=root)[0]["id"]
    assert lex_top != sem_top
    for w in (0.0, 1.0):  # even when fusion gives one ranker no weight at all
        monkeypatch.setattr(brain, "FUSION_LEXICAL_WEIGHT", w)
        ids = [r["id"] for r in brain.search_brain(q, k=2, root=root)]
        assert set(ids) == {lex_top, sem_top}, w


def test_filters_apply_in_every_mode(root, fake):
    _brain(root)
    for mode in ("lexical", "semantic", "hybrid"):
        res = brain.search_brain("customers cancel prices outreach", type="tactic", mode=mode, root=root)
        assert res and {r["type"] for r in res} == {"tactic"}, mode
        res = brain.search_brain("customers cancel prices outreach", topics=["leads"], mode=mode, root=root)
        assert [r["id"] for r in res] == ["leads-warm-outreach"], mode


def test_related_expansion_respects_filters_in_hybrid(root, fake):
    write_note(root, "offers-guarantees", "Guarantees", ["guarantees"], "Reverse risk with a guarantee.",
               related=["offers-net-sales-math"])
    write_note(root, "offers-net-sales-math", "Net sales math", ["metrics"], "Judge by sales minus refunds.",
               related=["offers-guarantees"], type_="concept")
    brain.build_index(root)
    ids = [r["id"] for r in brain.search_brain("guarantee", root=root)]
    assert ids[0] == "offers-guarantees" and "offers-net-sales-math" in ids
    assert all(r["type"] == "framework" for r in brain.search_brain("guarantee", type="framework", root=root))


def test_invalid_mode_rejected(root, fake):
    _brain(root)
    with pytest.raises(AlexAIError, match="mode must be one of"):
        brain.search_brain("x", mode="vector", root=root)


# ---------------------------------------------------------------- fallback

def test_falls_back_to_lexical_when_semantic_unavailable(root):
    _brain(root)  # conftest leaves semantic off
    q = "raise prices for buyers"
    lexical = brain.search_brain(q, mode="lexical", root=root)
    assert brain.search_brain(q, root=root) == lexical
    assert brain.search_brain(q, mode="hybrid", root=root) == lexical
    with pytest.raises(AlexAIError, match="semantic search is off"):
        brain.search_brain(q, mode="semantic", root=root)
    assert not (root / ".cache").exists()


def test_backend_missing_extra_reports_off(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_fastembed(name, *a, **kw):
        if name == "fastembed":
            raise ImportError("no fastembed", name="fastembed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_fastembed)
    semantic.reset()
    assert semantic.get_embedder() is None
    assert "semantic extra is not installed" in semantic.status()


def test_env_switch_disables_semantic(monkeypatch):
    semantic.reset()
    monkeypatch.setenv("ALEXAI_SEMANTIC", "off")
    assert semantic.get_embedder() is None and "ALEXAI_SEMANTIC" in semantic.status()


def test_index_reports_semantic_off_with_hint(root, capsys):
    from alexai.cli import main
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    res = brain.build_index(root)
    assert res["semantic"]["enabled"] is False and "pip install" in res["semantic"]["hint"]
    assert main(["brain", "index", "--root", str(root)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("semantic search off (disabled in tests)") and "[semantic]" in out[-1]


# ---------------------------------------------------------------- vector cache

def _cache(root, emb):
    with np.load(semantic.vector_path(emb.model_id, root)) as z:
        return json.loads(str(z["meta"])), z["ids"].tolist()


def test_index_builds_vectors_and_search_reuses_them(root, fake):
    _brain(root)
    meta, ids = _cache(root, fake)
    assert meta == {"model_id": fake.model_id, "dim": fake.dim, "recipe": semantic.RECIPE}
    # one vector per note plus one per question
    assert sorted(ids) == sorted(["offers-raise-prices", "money-models-continuity", "money-models-continuity",
                                  "leads-warm-outreach"])
    calls = len(fake.doc_calls)
    semantic._STATE.stores.clear()  # simulate a fresh process: read from disk, embed nothing
    brain.search_brain("customers", root=root)
    assert len(fake.doc_calls) == calls


def test_only_changed_notes_are_reembedded(root, fake):
    _brain(root)
    fake.doc_calls.clear()
    write_note(root, "leads-warm-outreach", "Warm Outreach", ["leads"], "Message every past client this week.",
               type_="tactic")
    brain.search_brain("clients", root=root)  # lazy refresh on search
    assert len(fake.doc_calls) == 1 and len(fake.doc_calls[0]) == 1
    assert "past client" in fake.doc_calls[0][0]
    # deleting a note drops its vectors; nothing is re-embedded
    (root / "brain/notes/offers-raise-prices.md").unlink()
    brain.build_index(root)
    assert len(fake.doc_calls) == 1
    assert "offers-raise-prices" not in _cache(root, fake)[1]


def test_model_change_reembeds_everything(root, fake):
    _brain(root)
    other = FakeEmbedder("fake/concepts-v2")
    semantic.set_embedder(other)
    brain.search_brain("customers", root=root)
    assert sum(len(c) for c in other.doc_calls) == 4  # every note and question, new model
    assert semantic.vector_path(other.model_id, root).exists()
    assert semantic.vector_path(fake.model_id, root).exists()  # old model's cache is left alone


def test_vectors_built_lazily_when_missing(root, fake):
    _brain(root)
    path = semantic.vector_path(fake.model_id, root)
    path.unlink()
    semantic._STATE.stores.clear()
    fake.doc_calls.clear()
    assert brain.search_brain("too pricey", mode="semantic", root=root)[0]["id"] == "offers-raise-prices"
    assert path.exists() and sum(len(c) for c in fake.doc_calls) == 4


def test_corrupt_or_foreign_cache_is_rebuilt(root, fake):
    _brain(root)
    path = semantic.vector_path(fake.model_id, root)
    path.write_bytes(b"not an npz")
    semantic._STATE.stores.clear()
    fake.doc_calls.clear()
    brain.search_brain("customers", root=root)
    assert sum(len(c) for c in fake.doc_calls) == 4 and _cache(root, fake)[0]["model_id"] == fake.model_id


def test_store_reports_best_matching_question(root, fake):
    write_note(root, "money-models-continuity", "Continuity offers", ["money-models"], "Reduce churn.",
               extra='questions:\n  - "How much should a membership cost?"\n  - "Why do my members cancel?"\n')
    write_note(root, "leads-warm-outreach", "Warm Outreach", ["leads"], "Contact people you know.", type_="tactic")
    brain.build_index(root)
    scores, best = semantic.note_scores("members quit", root, best_questions=True)
    assert best == {"money-models-continuity": 1, "leads-warm-outreach": None}
    assert scores == semantic.note_scores("members quit", root)


# ---------------------------------------------------------------- CLI

def test_cli_mode_flag(root, fake, capsys):
    from alexai.cli import main
    _brain(root)
    assert main(["brain", "search", "too pricey", "--mode", "semantic", "--json", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "offers-raise-prices"
    assert main(["brain", "search", "too pricey", "--mode", "lexical", "--json", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == []
    with pytest.raises(SystemExit):
        main(["brain", "search", "x", "--mode", "vector", "--root", str(root)])
    (root / "evals").mkdir()
    (root / "evals/questions.yaml").write_text(
        '- id: q1\n  style: plain\n  question: "my clients say it is too pricey"\n'
        '  expect_notes: [offers-raise-prices]\n', encoding="utf-8")
    capsys.readouterr()
    assert main(["eval", "retrieval", "--mode", "lexical", "--json", "--root", str(root)]) == 0
    lex = json.loads(capsys.readouterr().out)
    assert main(["eval", "retrieval", "--mode", "hybrid", "--json", "--root", str(root)]) == 0
    hyb = json.loads(capsys.readouterr().out)
    assert (lex["mode"], lex["hits"], hyb["mode"], hyb["hits"]) == ("lexical", 0, "hybrid", 1)
