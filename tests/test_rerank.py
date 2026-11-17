"""Optional cross-encoder reranking stage with a fake reranker: no model, no network."""
import pytest

from alexai import brain, rerank, semantic

from conftest import write_note
from test_semantic import FakeEmbedder, _brain


class FakeReranker:
    """Scores a text by how many of `favour`'s words it contains; records what it was shown."""

    model_id = "fake/reranker"

    def __init__(self, favour="", fail=False):
        self.favour = favour.lower().split()
        self.fail = fail
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query, texts):
        self.calls.append((query, list(texts)))
        if self.fail:
            raise RuntimeError("boom")
        return [float(sum(w in t.lower() for w in self.favour)) for t in texts]


@pytest.fixture
def fake():
    semantic.set_embedder(FakeEmbedder())


def test_blend_reorders_only_the_head():
    order = ["a", "b", "c", "d", "e"]
    ce = {"a": 0.0, "b": 0.1, "c": 9.0}
    out = rerank.blend(order, ce, depth=3, weight=1.0, k=60)
    assert out["c"] == pytest.approx(1 / 63 + 1 / 61)        # fused rank 3, reranker rank 1
    assert out["a"] == pytest.approx(1 / 61 + 1 / 63)
    assert out["d"] == pytest.approx(1 / 64) and out["e"] == pytest.approx(1 / 65)
    assert min(out[i] for i in "abc") > max(out["d"], out["e"])  # tail never jumps over the head
    ranked = brain._ranked(rerank.blend(order, ce, depth=3, weight=2.0))
    assert ranked[0] == "c" and ranked[3:] == ["d", "e"]


def test_note_text_uses_title_aliases_summary_and_best_question():
    doc = {"title": "Raise prices", "aliases": ["price increase"], "summary": "Charge more.",
           "questions": ["q1", "q2"]}
    assert rerank.note_text(doc, "q2") == "Raise prices (also called: price increase). Charge more. q2"
    assert rerank.note_text({"title": "T", "summary": "S"}, None) == "T. S"


def test_reranker_reorders_hybrid_head_with_closest_question(root, fake, monkeypatch):
    _brain(root)
    q = "why do members cancel"
    before = [r["id"] for r in brain.search_brain(q, k=3, root=root)]
    rr = FakeReranker(favour="outreach contact")
    rerank.set_reranker(rr)
    monkeypatch.setattr(rerank, "BLEND_WEIGHT", 3.0)  # let the reranker dominate for this check
    after = [r["id"] for r in brain.search_brain(q, k=3, root=root)]
    assert after.index("leads-warm-outreach") < before.index("leads-warm-outreach")
    assert sorted(after) == sorted(before)
    query, texts = rr.calls[-1]
    assert query == "why do members cancel"
    cont = next(t for t in texts if t.startswith("Continuity offers"))
    assert cont.endswith("Why do my members cancel?")  # the note's best-matching question is shown


def test_reranker_keeps_each_rankers_top_hit(root, fake):
    _brain(root)
    q = "outreach for clients who say it is pricey"
    lex_top = brain.search_brain(q, k=1, mode="lexical", root=root)[0]["id"]
    sem_top = brain.search_brain(q, k=1, mode="semantic", root=root)[0]["id"]
    rerank.set_reranker(FakeReranker(favour="continuity members"))
    ids = [r["id"] for r in brain.search_brain(q, k=2, root=root)]
    assert lex_top != sem_top and set(ids) == {lex_top, sem_top}


def test_reranker_only_in_hybrid_and_failures_fall_back(root, fake):
    _brain(root)
    q = "why do members cancel"
    plain = brain.search_brain(q, root=root)
    rr = FakeReranker(favour="outreach")
    rerank.set_reranker(rr)
    brain.search_brain(q, mode="lexical", root=root)
    brain.search_brain(q, mode="semantic", root=root)
    assert rr.calls == []
    rerank.set_reranker(FakeReranker(fail=True))
    assert brain.search_brain(q, root=root) == plain  # a crashing reranker never breaks search
    rerank.set_reranker(None)
    assert brain.search_brain(q, root=root) == plain


def test_reranker_without_semantic_uses_word_overlap_for_question(root):
    write_note(root, "money-models-continuity", "Continuity offers", ["money-models"], "Reduce churn.",
               extra='questions:\n  - "How do I price a membership?"\n  - "Why do my members cancel?"\n')
    brain.build_index(root)
    assert brain._best_question(["How do I price a membership?", "Why do my members cancel?"],
                                brain._query_terms("members cancel", root)) == "Why do my members cancel?"
    assert brain._best_question([], {"x": 1.0}) is None


def test_env_switch_and_model(monkeypatch):
    rerank.reset()
    monkeypatch.delenv("ALEXAI_RERANK", raising=False)
    assert rerank.enabled() is rerank.DEFAULT_ON
    monkeypatch.setenv("ALEXAI_RERANK", "off")
    assert rerank.get_reranker() is None and "ALEXAI_RERANK" in rerank.status()
    assert rerank.build()["enabled"] is False
    monkeypatch.setenv("ALEXAI_RERANK", "on")
    assert rerank.enabled()
    monkeypatch.setenv("ALEXAI_RERANK_MODEL", "some/model")
    assert rerank.configured_model() == "some/model"


def test_missing_model_reports_off_without_download(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEXAI_MODEL_DIR", str(tmp_path))  # empty model dir: nothing cached
    monkeypatch.setenv("ALEXAI_RERANK", "on")
    import builtins
    real_import = builtins.__import__

    def no_fastembed(name, *a, **kw):
        if name.startswith("fastembed"):
            raise ImportError("no fastembed", name="fastembed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_fastembed)
    rerank.reset()
    assert rerank.get_reranker() is None and "not installed" in rerank.status()
    assert list(tmp_path.iterdir()) == []


def test_index_mentions_reranker_only_when_on(root, capsys, monkeypatch):
    from alexai.cli import main
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    assert main(["brain", "index", "--root", str(root)]) == 0
    assert "reranker:" not in capsys.readouterr().out.splitlines()[-1]
    rerank.set_reranker(FakeReranker())
    res = brain.build_index(root)
    assert res["rerank"] == {"enabled": True, "model": "fake/reranker"}
    assert main(["brain", "index", "--root", str(root)]) == 0
    assert "reranker: fake/reranker" in capsys.readouterr().out
