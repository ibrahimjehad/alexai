from alexai import brain
from alexai.schema import validate_note_meta, validate_source_meta

from conftest import write_note

GOOD = {"id": "offers-value-equation", "type": "framework", "title": "The Value Equation",
        "author": "alex-hormozi", "topics": ["offers", "pricing"],
        "sources": [{"id": "hormozi-100m-offers-p03", "ref": "Part 3, ~12:40"}],
        "related": ["offers-grand-slam-offer"], "updated": "2026-11-16"}


def test_note_schema_accepts_spec_example():
    assert validate_note_meta(GOOD, "offers-value-equation") == []


def test_note_schema_rejects_bad_fields():
    bad = dict(GOOD, id="Value_Equation", type="idea", topics=[], sources=[{"id": "x"}], updated="16/11/2026")
    bad["extra"] = 1
    errs = " | ".join(validate_note_meta(bad, "offers-value-equation"))
    for needle in ("kebab", "does not match filename", "type 'idea'", "topics must not be empty",
                   "exactly 'id' and 'ref'", "YYYY-MM-DD", "unknown fields"):
        assert needle in errs


def test_source_schema():
    rec = {"id": "hormozi-100m-offers-p03", "author": "alex-hormozi", "collection": "100m-offers",
           "title": "Part 3", "kind": "podcast", "url": "https://x", "duration_sec": 1654, "notes": []}
    assert validate_source_meta(rec, "hormozi-100m-offers-p03") == []
    assert validate_source_meta(dict(rec, kind="tv"), "hormozi-100m-offers-p03")


def test_validate_cross_refs(root):
    write_note(root, "offers-value-equation", "The Value Equation", ["offers"], "Value = ...",
               related=["offers-missing"])
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", src="unknown-source")
    res = brain.validate(root)
    msgs = " | ".join(e["error"] for e in res["errors"])
    assert not res["ok"]
    assert "related note 'offers-missing' does not exist" in msgs
    assert "cites unknown source 'unknown-source'" in msgs


def test_search_ranks_relevant_note_first(root):
    write_note(root, "offers-value-equation", "The Value Equation", ["offers", "pricing"],
               "Value rises with dream outcome and perceived likelihood, falls with time delay and effort.")
    write_note(root, "leads-warm-outreach", "Warm Outreach", ["leads", "outreach"],
               "Contact people you already know and ask who they know.", type_="tactic")
    write_note(root, "offers-guarantees", "Guarantees", ["offers"], "Reverse risk so the price feels safe.",
               type_="tactic")
    assert brain.validate(root)["ok"]
    brain.build_index(root)
    res = brain.search_brain("how do I increase perceived value of my offer", k=3, root=root)
    assert res[0]["id"] == "offers-value-equation"
    assert brain.search_brain("outreach", root=root)[0]["id"] == "leads-warm-outreach"
    only_tactics = brain.search_brain("offer", type="tactic", root=root)
    assert {r["type"] for r in only_tactics} == {"tactic"}
    assert all("leads" in r["topics"] for r in brain.search_brain("people", topics=["leads"], root=root))
    assert (root / "brain/index.md").read_text().startswith("# Brain index")


def test_stemming_folds_word_variants():
    assert brain.tokenize("refer referral referrals referred") == ["refer"] * 4
    assert brain.tokenize("valuable values")[0] == brain.tokenize("value")[0]
    assert brain.tokenize("naming")[0] == brain.tokenize("name")[0]
    assert brain.tokenize("ads")[0] == brain.tokenize("ad")[0]
    assert brain.tokenize("How should I do the offer") == ["offer"]  # stopwords dropped


def test_search_matches_across_word_forms(root):
    write_note(root, "leads-referral-asks", "Ways to ask for referrals", ["referrals"],
               "Ask happy clients for introductions.", type_="tactic")
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    brain.build_index(root)
    res = brain.search_brain("how do I get customers to refer others", root=root)
    assert res[0]["id"] == "leads-referral-asks"


def test_related_expansion_pulls_in_linked_notes(root):
    write_note(root, "offers-guarantees", "Guarantees", ["guarantees"], "Reverse risk with a guarantee.",
               related=["offers-net-sales-math"])
    write_note(root, "offers-net-sales-math", "Net sales math", ["metrics"], "Judge by sales minus refunds.",
               related=["offers-guarantees"], type_="concept")
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    brain.build_index(root)
    res = brain.search_brain("guarantee", root=root)
    ids = [r["id"] for r in res]
    assert ids[0] == "offers-guarantees"
    assert "offers-net-sales-math" in ids and res[1]["score"] < res[0]["score"]
    assert "offers-scarcity" not in ids
    # filters still apply to expanded notes
    assert all(r["type"] == "framework" for r in brain.search_brain("guarantee", type="framework", root=root))


def test_synonyms_file_expands_query(root):
    write_note(root, "leads-core-four", "The Core Four", ["leads", "advertising"],
               "Warm outreach, content, cold outreach, paid ads.")
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    brain.build_index(root)
    assert brain.search_brain("which channel", root=root) == []
    (root / "brain/synonyms.yaml").write_text("channel: [core four, advertising]\n", encoding="utf-8")
    assert brain.search_brain("which channel", root=root)[0]["id"] == "leads-core-four"


def test_index_version_bump_rebuilds_stale_index(root):
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    (root / "brain/index.json").write_text('{"version": 1, "notes": []}', encoding="utf-8")
    assert brain.search_brain("scarcity", root=root)[0]["id"] == "offers-scarcity"


# ---------------------------------------------------------------- enrichment: questions + aliases

QS = ["What can I sell right after a customer buys?", "How do I get more money from each sale?",
      "What should I offer at checkout?"]


def test_schema_accepts_optional_questions_and_aliases():
    from alexai.schema import note_meta_warnings
    assert validate_note_meta(dict(GOOD, questions=QS, aliases=["upsell"]), "offers-value-equation") == []
    assert validate_note_meta(GOOD, "offers-value-equation") == []  # fields stay optional
    assert note_meta_warnings(dict(GOOD, questions=QS)) == []
    assert "no 'questions'" in note_meta_warnings(GOOD)[0]
    assert note_meta_warnings(dict(GOOD, type="example")) == []  # examples are not nagged
    assert "aim for 3-6" in note_meta_warnings(dict(GOOD, questions=QS[:1]))[0]


def test_schema_rejects_malformed_questions_and_aliases():
    errs = " | ".join(validate_note_meta(dict(GOOD, questions="why?", aliases=["ok", "", 3]),
                                         "offers-value-equation"))
    assert "questions must be a list of strings" in errs
    assert "aliases item '' must be a non-empty string" in errs and "aliases item 3" in errs
    assert "unknown fields" not in errs


def test_validate_warns_but_does_not_error_without_questions(root):
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    write_note(root, "offers-example", "An example", ["offers"], "A gym did this.", type_="example")
    res = brain.validate(root)
    assert res["ok"] and res["errors"] == []
    files = [w["file"] for w in res["warnings"] if "questions" in w["warning"]]
    assert files == ["brain/notes/offers-scarcity.md"]


def _enriched(qs=QS, aliases=("upsell", "add-on offer")):
    return ("questions:\n" + "".join(f'  - "{q}"\n' for q in qs)
            + "aliases: [" + ", ".join(aliases) + "]\n")


def test_questions_field_finds_note_with_no_shared_body_vocabulary(root):
    write_note(root, "offers-upsell-moment", "The Upsell Moment", ["money-models"],
               "Offer the next thing at the point of highest buying intent.", extra=_enriched())
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    write_note(root, "offers-guarantees", "Guarantees", ["offers"], "Reverse risk so a customer feels safe.",
               type_="tactic")
    brain.build_index(root)
    res = brain.search_brain("What can I sell right after a customer's first purchase?", root=root)
    assert res[0]["id"] == "offers-upsell-moment"
    # aliases are matched as alternative names
    assert brain.search_brain("add-on offer", root=root)[0]["id"] == "offers-upsell-moment"
    # return shape unchanged
    assert set(res[0]) == {"id", "title", "type", "topics", "sources", "summary", "score"}


def test_enrichment_fields_are_indexed_and_excluded_from_length(root):
    import json
    body = "Value rises with dream outcome."
    write_note(root, "offers-plain", "Value", ["offers"], body)
    write_note(root, "offers-rich", "Value", ["offers"], body, extra=_enriched())
    brain.build_index(root)
    idx = json.loads((root / "brain/index.json").read_text())
    assert idx["version"] == brain.INDEX_VERSION == 3
    plain, rich = sorted(idx["notes"], key=lambda d: d["id"])
    assert rich["questions"] == QS and rich["aliases"] == ["upsell", "add-on offer"]
    assert plain["questions"] == [] and plain["aliases"] == []
    assert rich["length"] == plain["length"]  # no length penalty for carrying questions/aliases
    assert rich["tf"][brain.stem("upsell")] == brain.FIELD_WEIGHTS["aliases"]
    # a query matching only the shared body scores both notes equally
    scores = {r["id"]: r["score"] for r in brain.search_brain("dream outcome", root=root)}
    assert scores["offers-plain"] == scores["offers-rich"]
    # index.md is unchanged in shape (no questions/aliases rendered)
    md = (root / "brain/index.md").read_text()
    assert "upsell" not in md and "checkout" not in md


def test_stale_v2_index_rebuilds_with_enrichment(root):
    write_note(root, "offers-upsell-moment", "The Upsell Moment", ["money-models"], "Offer more.",
               extra=_enriched())
    (root / "brain/index.json").write_text('{"version": 2, "n_docs": 0, "avgdl": 0, "df": {}, "notes": []}',
                                          encoding="utf-8")
    assert brain.search_brain("checkout", root=root)[0]["id"] == "offers-upsell-moment"


def test_get_and_list_include_enrichment_fields(root, capsys):
    import json
    from alexai.cli import main
    write_note(root, "offers-upsell-moment", "The Upsell Moment", ["money-models"], "Offer more.",
               extra=_enriched())
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    n = brain.get_note("offers-upsell-moment", root=root)
    assert n["questions"] == QS and n["aliases"] == ["upsell", "add-on offer"]
    assert brain.get_note("offers-scarcity", root=root)["questions"] == []
    assert main(["brain", "list", "--json", "--root", str(root)]) == 0
    listed = {x["id"]: x for x in json.loads(capsys.readouterr().out)}
    assert listed["offers-upsell-moment"]["aliases"] == ["upsell", "add-on offer"]
    assert listed["offers-scarcity"]["questions"] == []
    assert main(["brain", "get", "offers-upsell-moment", "--json", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["questions"] == QS
