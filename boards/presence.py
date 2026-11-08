"""Connected-user list for a board, stored in the Django cache."""

from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_TTL = 3600


def _key(board_id):
    return f"board-presence:{board_id}"


def presence_users(board_id):
    """Return [{id, username}, ...] or empty if the cache is down."""
    try:
        data = cache.get(_key(board_id)) or {}
    except Exception:
        logger.warning("Board presence cache is unavailable")
        return []
    return [{"id": key, "username": name} for key, name in data.items()]


def presence_join(board_id, user):
    """Record ``user`` as connected and return the current list."""
    try:
        key = _key(board_id)
        data = cache.get(key) or {}
        data[str(user.pk)] = user.username
        cache.set(key, data, _TTL)
        return [{"id": item, "username": name} for item, name in data.items()]
    except Exception:
        logger.warning("Board presence cache is unavailable")
        return []


def presence_leave(board_id, user):
    """Drop ``user`` from the connected list."""
    try:
        key = _key(board_id)
        data = cache.get(key) or {}
        data.pop(str(user.pk), None)
        cache.set(key, data, _TTL)
    except Exception:
        logger.warning("Board presence cache is unavailable")
