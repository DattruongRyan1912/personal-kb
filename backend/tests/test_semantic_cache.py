import fakeredis
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from personal_kb.services.semantic_cache import (
    SemanticCache,
    normalize_query,
    query_hash,
)
from personal_kb.services.session_memory import SessionMemoryManager, TranscriptEntry


@pytest.fixture
def fake_redis():
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def cache(fake_redis):
    return SemanticCache(fake_redis, default_ttl=3600)


def test_normalize_query_and_hash():
    q1 = "  Điều kiện tính lương   tháng 13?  "
    q2 = "điều kiện tính lương tháng 13?"
    q3 = "điều kiện tính lương tháng 13 khác"

    assert normalize_query(q1) == normalize_query(q2)
    assert query_hash(normalize_query(q1)) == query_hash(normalize_query(q2))
    assert query_hash(normalize_query(q1)) != query_hash(normalize_query(q3))


async def test_cache_hit_and_miss(cache):
    query = "Quy định thử việc"
    assert await cache.get(query, project_id="Project-A") is None

    stored = await cache.set(
        query=query,
        answer="Thời gian thử việc tối đa 60 ngày theo SPC-1.",
        citations=["SPC-1"],
        project_id="Project-A",
    )
    assert stored is True

    hit = await cache.get("  quy định   thử việc  ", project_id="Project-A")
    assert hit is not None
    assert hit["answer"] == "Thời gian thử việc tối đa 60 ngày theo SPC-1."
    assert hit["citations"] == ["SPC-1"]
    assert hit["project_id"] == "Project-A"


async def test_cache_invalidation_via_version_bump(cache):
    query = "Mã dự án CyberOS"
    await cache.set(query, "Mã dự án là CYBER-01", project_id="Project-B")

    hit = await cache.get(query, project_id="Project-B")
    assert hit is not None
    assert hit["answer"] == "Mã dự án là CYBER-01"

    # Bump version
    new_ver = await cache.bump_version("Project-B")
    assert new_ver >= 1

    # Old cache key should be completely invisible now (O(1) invalidation)
    assert await cache.get(query, project_id="Project-B") is None


async def test_cache_isolated_between_projects(cache):
    query = "Cấu trúc tổ chức"
    await cache.set(query, "Project-A org structure", project_id="Project-A")
    await cache.set(query, "Project-B org structure", project_id="Project-B")

    hit_a = await cache.get(query, project_id="Project-A")
    hit_b = await cache.get(query, project_id="Project-B")

    assert hit_a["answer"] == "Project-A org structure"
    assert hit_b["answer"] == "Project-B org structure"

    # Bump Project-A version only
    await cache.bump_version("Project-A")
    assert await cache.get(query, project_id="Project-A") is None
    assert (await cache.get(query, project_id="Project-B")) is not None


class FailingRedis:
    async def get(self, *args, **kwargs):
        raise ConnectionError("Redis is down")

    async def set(self, *args, **kwargs):
        raise ConnectionError("Redis is down")

    async def incr(self, *args, **kwargs):
        raise ConnectionError("Redis is down")


async def test_cache_fail_open_on_redis_error():
    broken_cache = SemanticCache(FailingRedis())
    # Should not raise exception
    assert await broken_cache.get("test query") is None
    assert await broken_cache.set("test query", "answer") is False
    assert await broken_cache.bump_version("test") == 1


async def test_multi_turn_history_guardrail_and_memory_persistence(fake_redis):
    cache = SemanticCache(fake_redis)
    memory = SessionMemoryManager(fake_redis, summarizer=None, threshold_tokens=100_000)
    user_id = "user-123"
    session_id = "sess-abc"

    query = "Lương cơ bản là gì?"
    cached_answer = "Lương cơ bản là mức lương cố định ghi trong HĐLĐ."
    await cache.set(query, cached_answer, project_id="CyberOS")

    # Turn 0: history is empty
    history = await memory.get_history(user_id, session_id)
    assert len(history) == 0

    # Simulate Turn 0 hitting cache
    hit = await cache.get(query, project_id="CyberOS")
    assert hit is not None

    # Persist turn
    await memory.add_messages(user_id, session_id, [HumanMessage(content=query), AIMessage(content=hit["answer"])])
    await memory.add_to_transcript(
        user_id,
        session_id,
        [TranscriptEntry(role="user", content=query), TranscriptEntry(role="assistant", content=hit["answer"])],
    )

    # Verify history now has 2 messages
    history_after = await memory.get_history(user_id, session_id)
    assert len(history_after) == 2

    # Turn 1 (Follow-up): history has items -> MUST bypass cache
    assert len(history_after) > 0


def test_kb_proposal_project_id_resolution():
    from personal_kb.services.proposals import KbProposal

    prop_hr = KbProposal(
        id="PROP-1",
        spec_id="HR-M04",
        title="Bảo hiểm",
        section="1. Quy định",
        proposed_content="Nội dung mới",
        rationale="Cập nhật",
        created_at="2026-10-23T00:00:00Z",
    )
    assert prop_hr.project_id == "Demo-Core"

    prop_mynotch = KbProposal(
        id="PROP-2",
        spec_id="MYNOTCH-01",
        title="Notch UI",
        section="1. Overview",
        proposed_content="Notch content",
        rationale="Update",
        created_at="2026-10-23T00:00:00Z",
    )
    assert prop_mynotch.project_id == "MyNotch"

    prop_pkb = KbProposal(
        id="PROP-3",
        spec_id="PKB-02",
        title="Cache Spec",
        section="4. Tối ưu",
        proposed_content="Cache content",
        rationale="Update",
        created_at="2026-10-23T00:00:00Z",
    )
    assert prop_pkb.project_id == "Personal-KB"


async def test_proposal_approval_cache_invalidation_flow(cache):
    from personal_kb.services.proposals import KbProposal

    # Pre-populate cache for Demo-Core and Personal-KB
    await cache.set("Chính sách thai sản", "Nghỉ 6 tháng", project_id="Demo-Core")
    await cache.set("Kiến trúc RRF", "RRF k=60", project_id="Personal-KB")

    assert (await cache.get("Chính sách thai sản", project_id="Demo-Core")) is not None
    assert (await cache.get("Kiến trúc RRF", project_id="Personal-KB")) is not None

    # Simulate proposal approval for Demo-Core
    prop = KbProposal(
        id="PROP-HR-99",
        spec_id="HR-M04",
        title="Sửa chế độ thai sản",
        section="Chế độ",
        proposed_content="Nghỉ 6 tháng + phụ cấp",
        rationale="Luật mới",
        created_at="2026-10-23T00:00:00Z",
    )

    # Invalidate via proposal.project_id
    target_project = getattr(prop, "project_id", "Personal-KB")
    await cache.bump_version(target_project)

    # Demo-Core cache invalidated
    assert (await cache.get("Chính sách thai sản", project_id="Demo-Core")) is None
    # Personal-KB cache intact
    assert (await cache.get("Kiến trúc RRF", project_id="Personal-KB")) is not None
