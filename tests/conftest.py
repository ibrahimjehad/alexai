import pytest

from alexai import manifest


@pytest.fixture
def root(tmp_path):
    for d in ("brain/notes", "brain/sources", "raw/audio", "raw/transcripts", "raw/pdfs", "projects"):
        (tmp_path / d).mkdir(parents=True)
    manifest.upsert([manifest.new_entry(id="hormozi-100m-offers-p03", author="alex-hormozi",
                                        collection="100m-offers", title="Part 3", kind="podcast",
                                        url="https://example.test/feed.xml",
                                        audio_url="https://example.test/p3.mp3", duration_sec=1654)],
                    tmp_path)
    return tmp_path


def write_note(root, nid, title, topics, body, related=(), type_="framework", src="hormozi-100m-offers-p03",
               extra=""):
    rel = "[" + ", ".join(related) + "]"
    (root / "brain/notes" / f"{nid}.md").write_text(
        f"---\nid: {nid}\ntype: {type_}\ntitle: {title}\nauthor: alex-hormozi\n"
        f"topics: [{', '.join(topics)}]\nsources:\n  - id: {src}\n    ref: \"Part 3, ~12:40\"\n"
        f"related: {rel}\nupdated: 2026-11-16\n{extra}---\n\n{body}\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_real_embedder():
    """Tests never load a real embedding model or reranker or touch the network: semantic search and
    reranking are off unless a test injects a fake with semantic.set_embedder / rerank.set_reranker."""
    from alexai import rerank, semantic
    semantic.set_embedder(None, reason="disabled in tests")
    rerank.set_reranker(None, reason="disabled in tests")
    yield
    semantic.reset()
    rerank.reset()
