"""Whitelist sanitizer rejects non-finite numbers."""

import math

import pytest

from boards.colors import USER_COLORS, user_color
from boards.protocol import ProtocolError, sanitize_properties


class TestProtocolNumbers:
    """NaN and Infinity are not legal coordinate values."""

    def test_nan_and_infinity_are_dropped(self):
        """Top-level non-finite numbers are not kept."""
        data = sanitize_properties(
            "rect",
            {
                "x": float("nan"),
                "y": float("inf"),
                "width": 10,
                "height": 8,
                "opacity": float("-inf"),
            },
        )
        assert "x" not in data
        assert "y" not in data
        assert "opacity" not in data
        assert data["width"] == 10
        assert data["height"] == 8

    def test_path_points_reject_nan(self):
        """A NaN inside path points is an invalid object."""
        with pytest.raises(ProtocolError, match="out of range"):
            sanitize_properties(
                "path",
                {"points": [[0, 0], [1, float("nan")]]},
            )

    def test_path_points_reject_infinity(self):
        """Infinity inside path points is an invalid object."""
        with pytest.raises(ProtocolError, match="out of range"):
            sanitize_properties(
                "path",
                {"points": [[0, 0], [float("inf"), 1]]},
            )

    def test_finite_float_is_kept(self):
        """Ordinary floats still pass."""
        data = sanitize_properties("rect", {"x": 1.5, "y": -2.0, "width": 3, "height": 4})
        assert data["x"] == 1.5
        assert math.isfinite(data["x"])


class TestUserColor:
    """Presence colors are stable and come from the server palette."""

    def test_same_id_is_stable(self):
        """The same user id always maps to the same hex."""
        first = user_color(7)
        second = user_color("7")
        assert first == second
        assert first in USER_COLORS

    def test_palette_has_twelve_colors(self):
        """The public palette is twelve contrasting hex values."""
        assert len(USER_COLORS) == 12
        assert len(set(USER_COLORS)) == 12
