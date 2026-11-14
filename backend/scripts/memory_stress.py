"""Context truncation QA for issue 2.1: send 20 very long chat turns into one session and check that what would be
sent to the main model never exceeds 4,000 tokens, while background summaries fold the older turns away.

Usage:  docker compose exec ai-backend python -m scripts.memory_stress [--turns 20]
Logs show "[MemoryManager] Context > 3000 tokens. Triggering background summarization..."; exits 1 if the cap broke.
"""

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage
from redis.asyncio import Redis

from personal_kb.core.config import get_settings
from personal_kb.core.prompts import load_prompt
from personal_kb.infrastructure.openai_client import build_openai_client
from personal_kb.services.session_memory import SUMMARY_NAME, SessionMemoryManager, count_tokens
from personal_kb.services.summarizer import LlmSummarizer

log = logging.getLogger("memory_stress")

MAX_CONTEXT_TOKENS = 4000


@dataclass(frozen=True)
class StressReport:
    turns: int
    max_context_tokens: int
    history_tokens: int
    history_has_summary: bool


def long_turn(i: int) -> tuple[HumanMessage, AIMessage]:
    question = (
        f"Câu hỏi {i}: hãy phân tích thật chi tiết luồng thanh toán SPC-2 và luồng đăng nhập SPC-1, các bảng "
        "orders, payments, users, login_sessions bị ghi khi nào, ai được gọi API nào, lỗi nào trả về mã nào. "
    ) * 6
    answer = (
        f"Trả lời {i}: luồng thanh toán tạo giao dịch qua POST /api/v1/payments/checkout, nhận IPN ở "
        "/api/v1/payments/vnpay/ipn, cập nhật payments rồi orders trong một transaction, cộng reward_points. "
    ) * 6
    return HumanMessage(question), AIMessage(answer)


async def stress(memory: SessionMemoryManager, *, user_id: str, session_id: str, turns: int) -> StressReport:
    peak = 0
    for i in range(1, turns + 1):
        await memory.add_messages(user_id, session_id, list(long_turn(i)))
        context = await memory.context_for_model(user_id, session_id)
        tokens = count_tokens(context)
        peak = max(peak, tokens)
        log.info("turn %2d: %d tokens would go to the main model", i, tokens)
    await memory.wait_idle()
    history = await memory.get_history(user_id, session_id)
    has_summary = bool(history) and getattr(history[0], "name", None) == SUMMARY_NAME
    return StressReport(turns, peak, count_tokens(history), has_summary)


async def main(turns: int) -> int:
    settings = get_settings()
    client = build_openai_client(settings)
    redis = Redis.from_url(settings.redis_url)
    summarizer = LlmSummarizer(
        client,
        model=settings.llm_model,
        prompt=load_prompt("session_summary"),
        reasoning_effort=settings.llm_reasoning_effort,
    )
    memory = SessionMemoryManager(redis, summarizer=summarizer, max_context_tokens=MAX_CONTEXT_TOKENS)
    session_id = f"stress-{int(time.time())}"
    try:
        report = await stress(memory, user_id="memory-stress", session_id=session_id, turns=turns)
    finally:
        await redis.aclose()
        await client.close()
    # token counts, not credentials: Semgrep's python-logger-credential-disclosure matches the word "tokens"
    log.info(  # nosemgrep
        "session %s: %d turns, peak %d tokens to the model (cap %d), history now %d tokens, summary: %s",
        session_id,
        report.turns,
        report.max_context_tokens,
        MAX_CONTEXT_TOKENS,
        report.history_tokens,
        report.history_has_summary,
    )
    return 0 if report.max_context_tokens <= MAX_CONTEXT_TOKENS else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--turns", type=int, default=20)
    raise SystemExit(asyncio.run(main(parser.parse_args().turns)))
