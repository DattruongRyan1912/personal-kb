"""Human Protocol namespace: /api/v1/human.

Encapsulates human-facing endpoints:
- /api/v1/human/chat: Conversational sessions, asking questions, and SSE streaming.
- /api/v1/human/specs: Frontmatter metadata for citation badges.
- /api/v1/human/memory: Semantic memory search for users.
"""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from personal_kb.api import chat, memory, specs

router = APIRouter(prefix="/api/v1/human", tags=["human-protocol"])

# Mirror human-facing routes under /api/v1/human/chat, /api/v1/human/specs, /api/v1/human/memory
for source_router, name in [(chat.router, "chat"), (specs.router, "specs"), (memory.router, "memory")]:
    sub = APIRouter(prefix=f"/{name}", dependencies=list(source_router.dependencies))
    for route in source_router.routes:
        if not isinstance(route, APIRoute):
            continue
        old_prefix = f"/api/v1/{name}"
        rel_path = route.path[len(old_prefix) :] if route.path.startswith(old_prefix) else route.path
        sub.add_api_route(
            rel_path,
            route.endpoint,
            methods=route.methods,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=["human-protocol"],
            dependencies=list(route.dependencies),
            responses=route.responses,
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            deprecated=route.deprecated,
            operation_id=f"human_{name}_{route.name}",
            name=f"human_{name}_{route.name}",
        )
    router.include_router(sub)
