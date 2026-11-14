import fakeredis

from personal_kb.services.session_memory import SessionMemoryManager
from scripts.memory_stress import long_turn, stress


class QuickSummaries:
    async def summarize(self, previous, messages):
        return f"tóm tắt {len(messages)} tin nhắn"


async def test_twenty_long_turns_never_send_more_than_the_cap():
    memory = SessionMemoryManager(fakeredis.FakeAsyncRedis(), summarizer=QuickSummaries())

    report = await stress(memory, user_id="u", session_id="s", turns=20)

    assert report.turns == 20
    assert report.max_context_tokens <= 4000
    assert report.history_has_summary


def test_a_turn_is_long():
    human, ai = long_turn(3)
    assert len(human.content) > 1000 and len(ai.content) > 1000
