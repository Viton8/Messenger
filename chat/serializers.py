"""Serializers for REST APIs in the chat application."""

from rest_framework import serializers

from .models import Chat, Message


class MessageSerializer(serializers.ModelSerializer):
    """Serialize stored chat messages for read APIs."""

    sender = serializers.CharField(source="sender.username", read_only=True)
    sender_id = serializers.UUIDField(read_only=True)
    kind = serializers.CharField(read_only=True)
    deleted = serializers.SerializerMethodField()
    edited_at = serializers.DateTimeField(read_only=True, allow_null=True)
    board_id = serializers.UUIDField(read_only=True, allow_null=True)
    board_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "sender",
            "sender_id",
            "content",
            "sent_at",
            "kind",
            "edited_at",
            "deleted",
            "board_id",
            "board_url",
        ]

    def get_deleted(self, obj):
        """Return True when the line is soft-deleted."""
        return bool(obj.deleted_at)

    def get_board_url(self, obj):
        """Return the board page path when a live board is attached."""
        if not obj.board_id:
            return None
        return f"/boards/{obj.board_id}/"

    def to_representation(self, instance):
        """Hide original text of a deleted message."""
        from .services import BOARD_DELETED_PLACEHOLDER, DELETED_PLACEHOLDER

        data = super().to_representation(instance)
        if instance.deleted_at:
            if instance.kind == Message.KIND_BOARD:
                data["content"] = BOARD_DELETED_PLACEHOLDER
            else:
                data["content"] = DELETED_PLACEHOLDER
            data["board_id"] = None
            data["board_url"] = None
        return data


class MessageCreateSerializer(serializers.ModelSerializer):
    """Validate inbound message bodies for create endpoints."""

    class Meta:
        model = Message
        fields = ["content"]

    def validate_content(self, value):
        """Strip whitespace and enforce non-empty, bounded length."""
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        if len(value) > 10000:
            raise serializers.ValidationError("Message exceeds maximum length.")
        return value


class ChatSerializer(serializers.ModelSerializer):
    """Serialize chat metadata for listing and direct-chat creation responses."""

    peer_username = serializers.SerializerMethodField()
    peer_id = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = [
            "id",
            "name",
            "is_group",
            "dm_pair_key",
            "peer_username",
            "peer_id",
            "last_message",
            "last_activity",
            "unread_count",
        ]
        read_only_fields = ["dm_pair_key"]

    def get_peer_username(self, obj):
        """Return the other user's username in a DM for the current viewer."""
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        if not obj.is_direct_message():
            return None
        other = obj.get_other_participant(request.user)
        return other.username if other else None

    def get_peer_id(self, obj):
        """Return the other user's id in a DM for the current viewer."""
        request = self.context.get("request")
        if not request or not getattr(request.user, "is_authenticated", False):
            return None
        if not obj.is_direct_message():
            return None
        other = obj.get_other_participant(request.user)
        return str(other.pk) if other else None

    def get_last_message(self, obj):
        """Return a short preview of the newest line, when the queryset annotated it."""
        from .services import BOARD_DELETED_PLACEHOLDER, DELETED_PLACEHOLDER, preview_text

        content = getattr(obj, "last_content", None)
        if getattr(obj, "last_deleted_at", None):
            if getattr(obj, "last_kind", None) == "board":
                content = BOARD_DELETED_PLACEHOLDER
            else:
                content = DELETED_PLACEHOLDER
        if not content:
            return None
        sent = getattr(obj, "last_sent_at", None)
        return {
            "sender": getattr(obj, "last_sender_name", "") or "",
            "content": preview_text(content, limit=160),
            "sent_at": sent.isoformat() if sent else None,
            "kind": getattr(obj, "last_kind", None) or "user",
        }

    def get_last_activity(self, obj):
        """Return the newest message time, or None for an empty chat."""
        sent = getattr(obj, "last_sent_at", None)
        return sent.isoformat() if sent else None

    def get_unread_count(self, obj):
        """Return annotated unread messages, or zero when the annotation is absent."""
        return int(getattr(obj, "unread_count", 0) or 0)


class DirectChatCreateSerializer(serializers.Serializer):
    """Request body for opening or retrieving a 1-on-1 chat."""

    other_user_id = serializers.UUIDField()


class GroupCreateSerializer(serializers.Serializer):
    """Request body for creating a named group."""

    name = serializers.CharField(max_length=60)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)
    avatar_url = serializers.URLField(required=False, allow_blank=True)


class GroupPatchSerializer(serializers.Serializer):
    """Request body for changing group name or description."""

    name = serializers.CharField(max_length=60, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)


class GroupMemberAddSerializer(serializers.Serializer):
    """Request body for adding a member by username."""

    username = serializers.CharField(max_length=150)


class GroupJoinSerializer(serializers.Serializer):
    """Request body for joining a group with an invite token."""

    token = serializers.CharField(max_length=64)


class GroupRoleSerializer(serializers.Serializer):
    """Request body for promoting or demoting a member."""

    role = serializers.ChoiceField(choices=("admin", "member"))


class MessageEditSerializer(serializers.Serializer):
    """Request body for editing a stored user message."""

    content = serializers.CharField()

    def validate_content(self, value):
        """Strip whitespace and enforce non-empty, bounded length."""
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        if len(value) > 10000:
            raise serializers.ValidationError("Message exceeds maximum length.")
        return value


class GroupMemberSerializer(serializers.Serializer):
    """One membership row for the group members API."""

    id = serializers.UUIDField()
    username = serializers.CharField()
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()
    initials = serializers.CharField()
    avatar_url = serializers.CharField(allow_blank=True)


class GroupDetailSerializer(serializers.Serializer):
    """Group metadata for retrieve responses."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField()
    avatar_url = serializers.CharField(allow_blank=True, allow_null=True)
    is_group = serializers.BooleanField()
    my_role = serializers.CharField()
    member_count = serializers.IntegerField()
    invite_url = serializers.CharField(allow_null=True)
