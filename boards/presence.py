"""Connected-user list for a board, keyed by WebSocket channel.

Production uses a Redis hash. Tests use an in-process map because CI has
no Redis.
"""

from __future__ import annotations

import json
import logging
import time

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache

logger = logging.getLogger(__name__)

_TTL = 3600
_TOUCH_EVERY = 60
_memory = {}
_memory_touched = {}
_redis_touched = {}


def _key(board_id):
    return f"board-presence:{board_id}"


def _payload(user):
    return json.dumps({"id": str(user.pk), "username": user.username})


def _unique_users(mapping):
    """Return unique users from channel_name -> JSON payload."""
    seen = {}
    for raw in mapping.values():
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            continue
        user_id = item.get("id")
        if user_id and user_id not in seen:
            seen[user_id] = {"id": user_id, "username": item.get("username") or ""}
    return list(seen.values())


class _MemoryHashes:
    def hset(self, key, field, value):
        _memory.setdefault(key, {})[field] = value

    def hdel(self, key, field):
        bucket = _memory.get(key)
        if bucket is None:
            return
        bucket.pop(field, None)
        if not bucket:
            _memory.pop(key, None)

    def hgetall(self, key):
        return dict(_memory.get(key) or {})

    def expire(self, key, ttl):
        del ttl
        _memory_touched[key] = time.monotonic()


class _RedisHashes:
    def __init__(self, client):
        self.client = client

    def hset(self, key, field, value):
        self.client.hset(key, field, value)

    def hdel(self, key, field):
        self.client.hdel(key, field)

    def hgetall(self, key):
        raw = self.client.hgetall(key) or {}
        out = {}
        for field, value in raw.items():
            if isinstance(field, bytes):
                field = field.decode("utf-8")
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            out[field] = value
        return out

    def expire(self, key, ttl):
        self.client.expire(key, ttl)


def _store():
    backend = caches["default"]
    if isinstance(backend, RedisCache):
        return _RedisHashes(backend._cache.get_client())
    return _MemoryHashes()


def _touch(store, key):
    now = time.monotonic()
    last = _redis_touched.get(key, 0)
    if now - last < _TOUCH_EVERY:
        return
    store.expire(key, _TTL)
    _redis_touched[key] = now


def presence_join(board_id, user, channel_name):
    """Record this socket and return ``(users, first_tab)``.

    ``first_tab`` is True when this user had no other open socket.
    """
    try:
        store = _store()
        key = _key(board_id)
        before = _unique_users(store.hgetall(key))
        store.hset(key, channel_name, _payload(user))
        _touch(store, key)
        users = _unique_users(store.hgetall(key))
        first = not any(item["id"] == str(user.pk) for item in before)
        return users, first
    except Exception:
        logger.warning("Board presence cache is unavailable")
        return [], True


def presence_leave(board_id, user, channel_name):
    """Drop this socket and return ``(users, last_tab)``.

    ``last_tab`` is True when this user has no remaining socket.
    """
    try:
        store = _store()
        key = _key(board_id)
        store.hdel(key, channel_name)
        _touch(store, key)
        users = _unique_users(store.hgetall(key))
        last = not any(item["id"] == str(user.pk) for item in users)
        return users, last
    except Exception:
        logger.warning("Board presence cache is unavailable")
        return [], True
