"""Builds the backing services from settings, for the API (main.py) and the scripts alike."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from redis.asyncio import Redis

from personal_kb.core.config import Settings
from personal_kb.core.prompts import load_prompt
from personal_kb.infrastructure.chat_model import build_chat_model, build_thorough_chat_model
from personal_kb.infrastructure.memory_backend import MemoryStores, build_memory
from personal_kb.infrastructure.openai_client import build_embedding_client, build_openai_client
from personal_kb.infrastructure.tracing import TracedOpenAI, Tracing, build_tracing
from personal_kb.services.agent import ChatAgent
from personal_kb.services.embedding import EmbeddingService
from personal_kb.services.query_entities import QueryEntityExtractor
from personal_kb.services.reranker import TeiReranker
from personal_kb.services.retrieval import HybridRetriever
from personal_kb.services.semantic_cache import SemanticCache
from personal_kb.services.session_memory import SessionMemoryManager
from personal_kb.services.spec_selector import SpecSelector
from personal_kb.services.summarizer import LlmSummarizer
from personal_kb.services.worklog import load_project_names
from personal_kb.tools.base import ToolContext
from personal_kb.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
TRACING_SHUTDOWN_SECONDS = 5  # flushing the last traces must not hold a stopping server


@dataclass(frozen=True)
class Services:
    openai: AsyncOpenAI | TracedOpenAI
    stores: MemoryStores  # the Postgres stores: chunks, documents, graph, worklog
    retriever: HybridRetriever
    tool_context: ToolContext
    memory: SessionMemoryManager
    chat_model: ChatOpenAI
    spec_selector: SpecSelector  # the specs a question needs, read whole on its first tool round
    thorough_chat_model: ChatOpenAI | None  # answers once the specs are read, when LLM_MODEL_THOROUGH is set
    tracing: Tracing  # Langfuse when LANGFUSE_* keys are set (issue 4.1)
    cache: SemanticCache | None = None


@asynccontextmanager
async def services(settings: Settings) -> AsyncIterator[Services]:
    async with build_memory(settings) as stores:
        tracing = build_tracing(settings)
        openai_client = build_openai_client(settings, tracing)
        embedding_client = build_embedding_client(settings, tracing)
        reranker_http = httpx.AsyncClient(base_url=settings.reranker_url, timeout=10)
        redis = Redis.from_url(settings.redis_url)
        retriever = HybridRetriever(
            embedder=EmbeddingService(
                embedding_client, model=settings.embedding_model, dimensions=settings.embedding_dimensions
            ),
            vectors=stores.vectors,
            term_extractor=QueryEntityExtractor(
                openai_client,
                model=settings.llm_model,
                prompt=load_prompt("query_entities"),
                reasoning_effort=settings.llm_reasoning_effort,
            ),
            graph=stores.graph,
            reranker=TeiReranker(reranker_http),
            graph_search=settings.graph_search,
            cache=redis,
        )
        memory = SessionMemoryManager(
            redis,
            summarizer=LlmSummarizer(
                openai_client,
                model=settings.llm_model,
                prompt=load_prompt("session_summary"),
                reasoning_effort=settings.llm_reasoning_effort,
            ),
        )
        cache = SemanticCache(redis)
        projects = load_project_names(settings.projects_config)
        if not projects:
            log.warning("No project map at %s: every worklog write will be rejected", settings.projects_config)
        try:
            yield Services(
                openai_client,
                stores,
                retriever,
                ToolContext(
                    retriever=retriever,
                    documents=stores.documents,
                    worklog=stores.worklog,
                    projects=projects,
                ),
                memory,
                build_chat_model(settings),
                SpecSelector(
                    openai_client,
                    model=settings.llm_model,
                    prompt=load_prompt("spec_selection"),
                    reasoning_effort=settings.llm_reasoning_effort,
                ),
                build_thorough_chat_model(settings),
                tracing,
                cache,
            )
        finally:
            await memory.wait_idle()
            await redis.aclose()
            await reranker_http.aclose()
            if embedding_client is not openai_client:
                await embedding_client.close()
            await openai_client.close()
            try:  # the SDK exports in the background; what is left is flushed here, within a bound
                await asyncio.wait_for(asyncio.to_thread(tracing.shutdown), TRACING_SHUTDOWN_SECONDS)
            except TimeoutError:
                log.warning(
                    "[Tracing] Langfuse took over %d s to flush: the last traces may be lost",
                    TRACING_SHUTDOWN_SECONDS,
                )


def build_chat_agent(built: Services, settings: Settings, tools: ToolRegistry, persona: str) -> ChatAgent:
    """The chat agent over the built services, the same for the API and the scripts."""
    return ChatAgent(
        model=built.chat_model,
        tools=tools,
        memory=built.memory,
        persona=persona,
        max_tool_calls=settings.agent_max_tool_calls,
        selector=built.spec_selector if settings.agent_read_specs else None,
        thorough_model=built.thorough_chat_model,
        tracing=built.tracing,
    )
