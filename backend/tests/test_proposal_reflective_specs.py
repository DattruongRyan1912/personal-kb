"""Anti-collision on proposals: a guardrail spec states the forbidden patterns, so it is not checked against them."""

from personal_kb.services.proposals import ProposalStore

GUARDRAIL = (
    "---\nid: HR-GOTCHAS\nproject: Demo-Core\nmemory_tier: reflective\n---\n\n"
    "- **[FORBIDDEN] [NC-HR-001]:** CẤM sử dụng kiểu `float`, `double` để tính tiền lương.\n"
)
SPEC = "---\nid: HR-M05\nproject: Demo-Core\n---\n\n# Lương\nLương cơ bản.\n"


def propose(tmp_path, spec_id, current, new):
    (tmp_path / f"{spec_id}.md").write_text(current, encoding="utf-8")
    store = ProposalStore(knowledge_dir=tmp_path)
    return store.create(
        spec_id=spec_id, title="t", section="", proposed_content=new, rationale="r", action="REPLACE_DOCUMENT"
    )


def test_a_proposal_to_a_reflective_spec_is_not_flagged_by_the_rules_it_states(tmp_path):
    # HR-GOTCHAS proposals were flagged NC-HR-001 for the word "float" in its own ban, and needed force (2026-10-25)
    prop = propose(tmp_path, "HR-GOTCHAS", GUARDRAIL, GUARDRAIL.replace("NC-HR-001", "NC-HR-001 (v2)"))

    assert prop.conflict_detected is False


def test_a_proposal_to_an_ordinary_spec_is_still_flagged(tmp_path):
    prop = propose(tmp_path, "HR-M05", SPEC, SPEC.replace("Lương cơ bản.", "Lương cơ bản dùng kiểu float."))

    assert prop.conflict_detected is True and prop.conflict_rule_id == "NC-HR-001"
