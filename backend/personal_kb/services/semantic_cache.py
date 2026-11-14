"""Semantic and Exact Query Cache on Redis (Phase 2, #297).

Provides sub-20ms instant responses for repeated single-turn queries.
- L1 Exact query matching with SHA-256 hash.
- O(1) Versioned Cache Invalidation:
  Key format: `kb:cache:{project_id}:{version}:{query_hash}`
  When documents/proposals change, `bump_version(project_id)` increments
  `kb:cache_version:{project_id}`, instantly invalidating all entries for that project.
- Multi-turn safety: Lookups ONLY occur on single-turn queries (empty history).
- High-availability fail-open: If Redis is down or encounters an error, operations fail gracefully.
"""

import hashlib
import json
import logging
import re
import time
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def normalize_query(query: str) -> str:
    """Normalize query by stripping whitespace, lowercase, and removing redundant spaces."""
    cleaned = re.sub(r"\s+", " ", query.strip().lower())
    return cleaned


def query_hash(normalized_query: str) -> str:
    """Generate SHA-256 digest of normalized query."""
    return hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()


class SemanticCache:
    def __init__(self, redis: Redis, default_ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis = redis
        self._default_ttl = default_ttl

    async def get_version(self, project_id: str) -> str:
        """Fetch current epoch version for the project (defaults to '0')."""
        try:
            val = await self._redis.get(f"kb:cache_version:{project_id}")
            if val is None:
                return "0"
            return val.decode("utf-8") if isinstance(val, bytes) else str(val)
        except Exception as exc:
            log.warning("[SemanticCache] Failed to fetch cache version for %s: %s", project_id, exc)
            return "0"

    async def bump_version(self, project_id: str) -> int:
        """Increment project cache version, atomically invalidating all project cache keys in O(1)."""
        try:
            ver = await self._redis.incr(f"kb:cache_version:{project_id}")
            log.info("[SemanticCache] Bumped cache version for project %s to %s", project_id, ver)
            return int(ver)
        except Exception as exc:
            log.warning("[SemanticCache] Failed to bump cache version for %s: %s", project_id, exc)
            return 1

    def _cache_key(self, project_id: str, version: str, q_hash: str) -> str:
        return f"kb:cache:{project_id}:{version}:{q_hash}"

    async def get(self, query: str, project_id: str = "Personal-KB") -> dict[str, Any] | None:
        """Look up cached response for single-turn query. Returns None on cache miss or error."""
        normalized = normalize_query(query)
        if not normalized:
            return None
        q_h = query_hash(normalized)
        try:
            version = await self.get_version(project_id)
            key = self._cache_key(project_id, version, q_h)
            raw = await self._redis.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            log.info("[SemanticCache] HIT for '%s' (project: %s, hash: %s)", normalized[:40], project_id, q_h[:8])
            return data
        except Exception as exc:
            log.warning("[SemanticCache] Read error: %s", exc)
            return None

    async def set(
        self,
        query: str,
        answer: str,
        citations: list[str] | None = None,
        project_id: str = "Personal-KB",
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store response in cache under current project epoch version."""
        normalized = normalize_query(query)
        if not normalized or not answer:
            return False
        q_h = query_hash(normalized)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        try:
            version = await self.get_version(project_id)
            key = self._cache_key(project_id, version, q_h)
            payload = json.dumps(
                {
                    "query": query,
                    "normalized": normalized,
                    "answer": answer,
                    "citations": citations or [],
                    "project_id": project_id,
                    "version": version,
                    "cached_at": time.time(),
                },
                ensure_ascii=False,
            )
            await self._redis.set(key, payload, ex=ttl)
            log.info("[SemanticCache] SET for '%s' (project: %s, ttl: %ds)", normalized[:40], project_id, ttl)
            return True
        except Exception as exc:
            log.warning("[SemanticCache] Write error: %s", exc)
            return False
