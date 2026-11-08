"""Stable user colors for board cursors and presence.

The browser does not pick a color. The same user id always maps to the
same palette entry.
"""

from __future__ import annotations

USER_COLORS = (
    "#e53935",
    "#d81b60",
    "#8e24aa",
    "#5e35b1",
    "#3949ab",
    "#1e88e5",
    "#00897b",
    "#43a047",
    "#c0ca33",
    "#fb8c00",
    "#f4511e",
    "#6d4c41",
)


def user_color(user_id):
    """Return a palette hex for ``user_id``."""
    text = str(user_id)
    acc = 0
    for char in text:
        acc = (acc * 31 + ord(char)) & 0xFFFFFFFF
    return USER_COLORS[acc % len(USER_COLORS)]


def public_user(user=None, *, user_id=None, username=""):
    """JSON user object with a server-assigned color."""
    if user is not None:
        uid = str(user.pk)
        name = user.username
    else:
        uid = str(user_id)
        name = username or ""
    return {"id": uid, "username": name, "color": user_color(uid)}


def colored_users(users):
    """Add colors to presence rows that only have id and username."""
    out = []
    for item in users or []:
        out.append(
            public_user(
                user_id=item.get("id"),
                username=item.get("username") or "",
            )
        )
    return out
