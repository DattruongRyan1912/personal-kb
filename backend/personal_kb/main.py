"""Application factory. Run with: uvicorn personal_kb.main:create_app --factory"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from personal_kb.api import agent, chat, data_hub, dev, health, human, memory, proposals, specs, system, worklog
from personal_kb.bootstrap import build_chat_agent, services
from personal_kb.core.auth import SupabaseJwtVerifier
from personal_kb.core.config import Settings, get_settings
from personal_kb.core.exceptions import register_exception_handlers
from personal_kb.core.prompts import load_prompt
from personal_kb.tools.registry import ToolRegistry


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()  # fail-fast: invalid settings stop the server here
    # uvicorn configures only its own loggers; without this the app's INFO lines (search timings) are dropped
    logging.getLogger("personal_kb").setLevel(logging.INFO)
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("personal_kb.main")
    # tools are validated here: a tool with a missing or terse description stops the app at startup (issue 2.2)
    tools = ToolRegistry.discover()
    log.info("[ToolRegistry] tools: %s", json.dumps(tools.openai_schemas(), ensure_ascii=False))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with services(settings) as built:
            app.state.stores = built.stores
            app.state.retriever = built.retriever
            app.state.tool_context = built.tool_context
            app.state.memory = built.memory
            app.state.cache = built.cache
            app.state.agent = build_chat_agent(built, settings, tools, load_prompt("agent_persona").system)
            yield

    app = FastAPI(title="Personal KB Core", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.tools = tools
    secret = settings.supabase_jwt_secret
    app.state.auth = SupabaseJwtVerifier(
        supabase_url=settings.supabase_url, jwt_secret=secret.get_secret_value() if secret else None
    )
    register_exception_handlers(app)
    if settings.cors_origin_list:  # the chat UI is served from another origin (issue 3.2)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.include_router(health.router)
    app.include_router(system.router)
    app.include_router(memory.router)
    app.include_router(chat.router)
    app.include_router(specs.router)
    app.include_router(proposals.router)
    app.include_router(data_hub.router)
    app.include_router(agent.router)
    app.include_router(worklog.router)
    app.include_router(human.router)
    if settings.dev_login:
        log.warning("[Auth] DEV_LOGIN is on: POST /api/v1/dev/token signs in a dev user (local only)")
        app.include_router(dev.router)
    return app
