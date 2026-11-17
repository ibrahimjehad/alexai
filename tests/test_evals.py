import json

from alexai import brain, evals
from alexai.cli import main

from conftest import write_note

QUESTIONS = """
- id: referrals
  mode: strategy
  question: "How do I get customers to refer others?"
  expect_notes: [leads-referral-asks, leads-missing-note]
- id: gap
  mode: strategy
  question: "Equity for my first hire?"
  expect_notes: []
"""


def _fixture(root):
    write_note(root, "leads-referral-asks", "Ways to ask for referrals", ["referrals"], "Ask happy clients.")
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    (root / "evals").mkdir()
    (root / "evals/questions.yaml").write_text(QUESTIONS, encoding="utf-8")
    brain.build_index(root)


def test_retrieval_eval_counts_hits_and_misses(root):
    _fixture(root)
    res = evals.retrieval(k=3, root=root)
    assert (res["hits"], res["expected"], res["recall"]) == (1, 2, 0.5)
    [q] = res["questions"]  # questions without expect_notes are skipped
    assert q["hits"] == ["leads-referral-asks"] and q["misses"] == ["leads-missing-note"]
    text = evals.format_retrieval(res)
    assert "MISS  leads-missing-note" in text and "recall@3: 1/2 = 50.0%" in text


def test_eval_retrieval_cli(root, capsys):
    _fixture(root)
    assert main(["eval", "retrieval", "--k", "2", "--json", "--root", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["k"] == 2 and out["recall"] == 0.5
    assert main(["eval", "retrieval", "--root", str(root)]) == 0
    assert "recall@8: 1/2" in capsys.readouterr().out


def test_eval_retrieval_cli_missing_file(root, capsys):
    assert main(["eval", "retrieval", "--root", str(root)]) == 1
    assert "questions file not found" in capsys.readouterr().err


STYLED = """
- id: a
  question: "How do I get customers to refer others?"
  style: framework-words
  expect_notes: [leads-referral-asks]
- id: b
  question: "scarcity"
  style: framework-words
  expect_notes: [offers-scarcity, leads-missing-note]
- id: c
  question: "nothing in common here"
  style: plain
  expect_notes: [offers-scarcity]
"""


def test_retrieval_reports_mrr_and_style_breakdown(root, capsys):
    _fixture(root)
    path = root / "evals/styled.yaml"
    path.write_text(STYLED, encoding="utf-8")
    res = evals.retrieval(k=3, questions=path, root=root)
    assert [q["rr"] for q in res["questions"]] == [1.0, 1.0, 0.0]
    assert res["mrr"] == round(2 / 3, 4)
    assert res["by_style"]["framework-words"] == {"questions": 2, "hits": 2, "expected": 3,
                                                  "recall": round(2 / 3, 4), "mrr": 1.0}
    assert res["by_style"]["plain"] == {"questions": 1, "hits": 0, "expected": 1, "recall": 0.0, "mrr": 0.0}
    text = evals.format_retrieval(res)
    assert "recall@3: 2/4 = 50.0% over 3 questions" in text
    assert "MRR@3: 0.667" in text
    assert "style framework-words: recall 2/3 = 66.7%, MRR 1.000 over 2 questions" in text
    assert main(["eval", "retrieval", "--questions", str(path), "--root", str(root)]) == 0
    assert "style plain: recall 0/1" in capsys.readouterr().out


def test_retrieval_without_styles_has_empty_breakdown(root):
    _fixture(root)
    res = evals.retrieval(k=3, root=root)
    assert res["by_style"] == {} and res["mrr"] == 1.0
    assert "style " not in evals.format_retrieval(res)


LOOSE = """
- id: a
  style: plain
  question: "How do I get customers to refer others?"
  expect_notes: [leads-missing-note, leads-referral-asks]
- id: b
  style: plain
  question: "scarcity"
  expect_notes: [offers-guarantees]
  accept_notes: [offers-scarcity]
- id: c
  style: jargon
  question: "refer referrals"
  expect_notes: [offers-net-sales-math]
"""


def test_lenient_reachable_and_solved_metrics(root, capsys):
    write_note(root, "leads-referral-asks", "Ways to ask for referrals", ["referrals"], "Ask happy clients.",
               related=["offers-net-sales-math"])
    write_note(root, "offers-scarcity", "Scarcity", ["offers"], "Limit supply.", type_="tactic")
    write_note(root, "offers-guarantees", "Guarantees", ["guarantees"], "Reverse risk.")
    write_note(root, "offers-net-sales-math", "Net sales math", ["metrics"], "Sales minus refunds.", type_="concept")
    (root / "evals").mkdir()
    path = root / "evals/loose.yaml"
    path.write_text(LOOSE, encoding="utf-8")
    brain.build_index(root)
    res = evals.retrieval(k=1, questions=path, root=root)
    a, b, c = res["questions"]
    assert a["retrieved"] == ["leads-referral-asks"] and (a["lenient_hits"], a["reachable_hits"]) == (1, 1)
    assert b["hits"] == [] and b["accept"] == ["offers-scarcity"] and b["lenient_hits"] == 1  # accepted stand-in
    assert c["hits"] == [] and c["reachable_hits"] == 1  # linked from the top result via `related`
    assert (res["hits"], res["lenient_hits"], res["reachable_hits"], res["solved"]) == (1, 2, 2, 1)
    assert res["style_extras"] == {"jargon": {"questions": 1, "solved": 0, "lenient_hits": 0, "reachable_hits": 1},
                                   "plain": {"questions": 2, "solved": 1, "lenient_hits": 2, "reachable_hits": 1}}
    text = evals.format_retrieval(res)
    assert "recall@1: 1/4 = 25.0% over 3 questions" in text  # existing lines are unchanged
    assert "lenient recall@1 (expected or an accept_note in top 1): 2/4 = 50.0%" in text
    assert "reachable@1 (in top 1 or linked from the top 3): 2/4 = 50.0%" in text
    assert "questions solved@1 (at least one expected note in top 1): 1/3 = 33.3%" in text
    assert "style plain: solved 1/2, lenient 2, reachable 1" in text
