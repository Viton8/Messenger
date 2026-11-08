"""Whitelist validation for board drawing ops.

Unknown types reject the whole message. Unknown property keys are dropped.
Numbers outside range and illegal colors drop that one field, except where
the field is required for the op to make sense (path points, object id).
"""

from __future__ import annotations

import math
import re
import uuid

ALLOWED_TYPES = frozenset(
    {"rect", "ellipse", "line", "path", "textbox", "arrow", "sticker"}
)
FONT_FAMILIES = frozenset(
    {
        "sans-serif",
        "serif",
        "monospace",
        "Georgia",
        "Verdana",
        "Comic Sans MS",
    }
)
COMMON_KEYS = frozenset(
    {
        "x",
        "y",
        "width",
        "height",
        "angle",
        "scaleX",
        "scaleY",
        "fill",
        "stroke",
        "strokeWidth",
        "opacity",
    }
)
LINE_KEYS = COMMON_KEYS | frozenset({"x1", "y1", "x2", "y2"})
PATH_KEYS = COMMON_KEYS | frozenset({"points"})
TEXT_KEYS = COMMON_KEYS | frozenset({"text", "fontSize", "fontFamily"})
KEYS_BY_TYPE = {
    "rect": COMMON_KEYS,
    "ellipse": COMMON_KEYS,
    "line": LINE_KEYS,
    "arrow": LINE_KEYS,
    "path": PATH_KEYS,
    "textbox": TEXT_KEYS,
    "sticker": TEXT_KEYS,
}
TRANSIENT_KEYS = frozenset({"x", "y", "angle", "scaleX", "scaleY"})
COORD_MIN, COORD_MAX = -100000, 100000
SIZE_MIN, SIZE_MAX = 0, 20000
ANGLE_MIN, ANGLE_MAX = -360, 360
SCALE_MIN, SCALE_MAX = 0.01, 100
OPACITY_MIN, OPACITY_MAX = 0, 1
STROKE_MIN, STROKE_MAX = 0, 80
FONT_SIZE_MIN, FONT_SIZE_MAX = 8, 400
PATH_POINTS_MAX = 500
TEXT_MAX = 2000
CLIENT_OP_ID_MAX = 64
COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


class ProtocolError(ValueError):
    """A rejected board message. ``code`` is sent to the client."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def parse_object_id(raw):
    """Return a UUID or raise ProtocolError."""
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProtocolError("invalid_id", "Object id must be a UUID.") from exc


def parse_client_op_id(raw):
    """Return a 1–64 character client op id."""
    if raw is None:
        raise ProtocolError("bad_payload", "client_op_id is required.")
    value = str(raw).strip()
    if not value or len(value) > CLIENT_OP_ID_MAX:
        raise ProtocolError("bad_payload", "client_op_id must be 1–64 characters.")
    return value


def _is_number(value):
    return (type(value) is int or type(value) is float) and math.isfinite(value)


def _clamp_number(value, lo, hi):
    if not _is_number(value):
        return None
    if value < lo or value > hi:
        return None
    return value


def _color(value):
    if value == "transparent":
        return value
    if isinstance(value, str) and COLOR_RE.match(value):
        return value
    return None


def _points(value):
    if not isinstance(value, list):
        raise ProtocolError("invalid_object", "Path points must be a list.")
    if len(value) > PATH_POINTS_MAX:
        raise ProtocolError(
            "invalid_object",
            "Path points cannot exceed %d." % PATH_POINTS_MAX,
        )
    points = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ProtocolError("invalid_object", "Each path point must be [x, y].")
        x = _clamp_number(item[0], COORD_MIN, COORD_MAX)
        y = _clamp_number(item[1], COORD_MIN, COORD_MAX)
        if x is None or y is None:
            raise ProtocolError("invalid_object", "Path point is out of range.")
        points.append([x, y])
    return points


def sanitize_properties(obj_type, raw, *, partial=False):
    """Return a dict of allowed properties for ``obj_type``.

    Args:
        obj_type: Whitelisted type name.
        raw: Incoming mapping.
        partial: When True, missing keys are allowed (patch/transient).

    Returns:
        dict: Clean properties (no ``type``).

    Raises:
        ProtocolError: Unknown type, or required path/text rules fail.
    """
    if obj_type not in ALLOWED_TYPES:
        raise ProtocolError("invalid_type", "Unknown object type.")
    if not isinstance(raw, dict):
        raise ProtocolError("invalid_object", "Object data must be an object.")
    allowed = KEYS_BY_TYPE[obj_type]
    out = {}
    for key, value in raw.items():
        if key == "type":
            continue
        if key not in allowed:
            continue
        cleaned = _clean_field(key, value)
        if cleaned is not None:
            out[key] = cleaned
    if not partial and obj_type == "path" and "points" not in out:
        raise ProtocolError("invalid_object", "Path objects need points.")
    return out


def _clean_field(key, value):
    if key in ("x", "y", "x1", "y1", "x2", "y2"):
        return _clamp_number(value, COORD_MIN, COORD_MAX)
    if key in ("width", "height"):
        return _clamp_number(value, SIZE_MIN, SIZE_MAX)
    if key == "angle":
        return _clamp_number(value, ANGLE_MIN, ANGLE_MAX)
    if key in ("scaleX", "scaleY"):
        return _clamp_number(value, SCALE_MIN, SCALE_MAX)
    if key == "opacity":
        return _clamp_number(value, OPACITY_MIN, OPACITY_MAX)
    if key == "strokeWidth":
        return _clamp_number(value, STROKE_MIN, STROKE_MAX)
    if key == "fontSize":
        return _clamp_number(value, FONT_SIZE_MIN, FONT_SIZE_MAX)
    if key in ("fill", "stroke"):
        return _color(value)
    if key == "fontFamily":
        if isinstance(value, str) and value in FONT_FAMILIES:
            return value
        return None
    if key == "text":
        if not isinstance(value, str):
            raise ProtocolError("invalid_object", "Text must be a string.")
        if len(value) > TEXT_MAX:
            raise ProtocolError(
                "invalid_object",
                "Text cannot exceed %d characters." % TEXT_MAX,
            )
        return value
    if key == "points":
        return _points(value)
    return None


def extract_type(op):
    """Read the object type from an add op."""
    if not isinstance(op, dict):
        raise ProtocolError("bad_payload", "Each op must be an object.")
    raw = op.get("type")
    data = op.get("data") if isinstance(op.get("data"), dict) else {}
    if raw is None:
        raw = data.get("type")
    if not isinstance(raw, str) or raw not in ALLOWED_TYPES:
        raise ProtocolError("invalid_type", "Unknown object type.")
    return raw


def sanitize_transient_patch(raw):
    """Keep only live-drag numeric fields."""
    if not isinstance(raw, dict):
        raise ProtocolError("invalid_object", "Patch must be an object.")
    out = {}
    for key in TRANSIENT_KEYS:
        if key not in raw:
            continue
        cleaned = _clean_field(key, raw[key])
        if cleaned is not None:
            out[key] = cleaned
    return out
