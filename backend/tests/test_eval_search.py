import json
from pathlib import Path

from scripts.eval_search import hit_at, reciprocal_rank

CASES = Path(__file__).resolve().parents[1] / "scripts" / "search_cases.json"


def test_a_hit_must_be_within_the_first_k():
    assert hit_at(["A", "B"], ["B"], 1) is False
    assert hit_at(["A", "B"], ["B"], 2) is True


def test_the_rank_of_the_first_wanted_spec_scores_the_case():
    assert reciprocal_rank(["A", "B"], ["B"]) == 0.5
    assert reciprocal_rank(["A", "B"], ["C"]) == 0.0


def test_an_off_topic_question_scores_only_when_nothing_comes_back():
    assert hit_at([], [], 5) is True
    assert hit_at(["A"], [], 5) is False
    assert reciprocal_rank([], []) == 1.0
    assert reciprocal_rank(["A"], []) == 0.0


def test_every_case_names_a_query_a_project_and_its_kind():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    kinds = {"accent", "no-accent", "prose", "typo", "keyword", "off-topic"}

    assert len(cases) >= 18
    assert all(c["query"] and c["project"] and c["kind"] in kinds for c in cases)
    assert all((c["want"] == []) == (c["kind"] == "off-topic") for c in cases)


def test_every_spec_in_knowledge_is_the_answer_of_some_case():
    # wrong HR titles went unnoticed until content-labelled cases asked about them: a spec no case asks about has no
    # check at all (2026-10-25)
    from personal_kb.services.knowledge_files import spec_files, spec_id_of

    specs = {spec_id_of(p) for p in spec_files(Path(__file__).resolve().parents[2] / "knowledge")}
    wanted = {spec for c in json.loads(CASES.read_text(encoding="utf-8")) for spec in c["want"]}

    assert sorted(specs - wanted) == []
