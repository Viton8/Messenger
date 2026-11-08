"""Serializers for board metadata APIs."""

from rest_framework import serializers


class BoardCreateSerializer(serializers.Serializer):
    """Request body for creating a named board."""

    title = serializers.CharField(max_length=80)


class BoardPatchSerializer(serializers.Serializer):
    """Request body for renaming or locking a board."""

    title = serializers.CharField(max_length=80, required=False)
    is_locked = serializers.BooleanField(required=False)
