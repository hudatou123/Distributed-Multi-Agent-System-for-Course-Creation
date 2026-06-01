"""Redis-backed distributed cache for the orchestrator.

A finished course is cached keyed by its topic. A repeated request for the
same topic is served from Redis in milliseconds, skipping the entire
Researcher -> Judge -> ContentBuilder pipeline.

This cache is a pure optimization. Because Cloud Run runs multiple stateless
orchestrator instances, an external shared cache (Redis) is what lets a cache
entry written by one instance be reused by another. If Redis is unreachable,
every operation degrades silently to a miss so the pipeline keeps working.
"""
import hashlib
import os

import redis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
_TTL_SECONDS = 60 * 60 * 24  # Keep a built course for 24 hours.

# A single shared client. redis-py connects lazily and is safe to reuse, so an
# unreachable Redis does not blow up at import time, only on the first call
# (which we catch below).
_client = redis.Redis.from_url(
    _REDIS_URL, decode_responses=True, socket_connect_timeout=2
)


def make_course_key(topic: str) -> str:
    """Build a cache key from a topic, normalized so 'Kafka' == ' kafka '."""
    normalized = topic.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"course:{digest}"


def get_cached(key: str) -> str | None:
    """Return the cached value, or None on miss or any Redis error."""
    try:
        return _client.get(key)
    except redis.RedisError as exc:
        print(f"[cache] get failed ({exc}); treating as miss")
        return None


def set_cached(key: str, value: str) -> None:
    """Store a value with a TTL. Silently no-ops if Redis is unreachable."""
    if not value:
        return
    try:
        _client.setex(key, _TTL_SECONDS, value)
        print(f"[cache] stored {key} (ttl={_TTL_SECONDS}s)")
    except redis.RedisError as exc:
        print(f"[cache] set failed ({exc}); skipping")
