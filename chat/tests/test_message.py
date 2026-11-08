"""Tests for the Message model in the chat app."""

import pytest
from django.utils import timezone

from chat.models import Chat, Message


@pytest.mark.django_db
class TestMessageModel:
    """Test suite for Message model with chat-based messaging."""

    def test_message_creation_in_group_chat(self, test_user):
        """Messages are created correctly for group chats."""
        chat = Chat.objects.create(name="Group Chat", is_group=True)
        message = Message.objects.create(
            sender=test_user,
            chat=chat,
            content="Hello group chat!",
        )
        assert message.sender == test_user
        assert message.chat == chat
        assert message.chat.is_group is True
        assert message.content == "Hello group chat!"
        assert message.sent_at is not None

    def test_message_creation_in_private_chat(self, test_user):
        """Messages are created correctly for private chats."""
        private_chat = Chat.objects.create(name="Private Chat", is_group=False)
        message = Message.objects.create(
            sender=test_user,
            chat=private_chat,
            content="Hello in private chat!",
        )
        assert message.sender == test_user
        assert message.chat == private_chat
        assert message.chat.is_group is False
        assert message.content == "Hello in private chat!"
        assert message.sent_at is not None

    def test_message_uuid_generation(self, test_user):
        """UUID is automatically generated for messages."""
        chat = Chat.objects.create(name="UUID Chat", is_group=True)
        message = Message.objects.create(sender=test_user, chat=chat, content="Test")
        assert message.id is not None
        assert len(str(message.id)) == 36

    def test_message_sent_at_auto_generation(self, test_user):
        """sent_at timestamp is automatically set on creation."""
        chat = Chat.objects.create(name="Timestamp Chat", is_group=True)
        before_creation = timezone.now()
        message = Message.objects.create(
            sender=test_user, chat=chat, content="Test timestamp"
        )
        assert message.sent_at is not None
        assert message.sent_at >= before_creation

    def test_message_str_representation_short_content(self, test_user):
        """String representation of Message for short content."""
        chat = Chat.objects.create(name="Str Chat Short", is_group=True)
        short_content = "Short message"
        message = Message.objects.create(
            sender=test_user, chat=chat, content=short_content
        )
        assert str(message) == f"{test_user.username}: {short_content}"

    def test_message_str_representation_long_content_truncated(self, test_user):
        """Long content is truncated in string representation."""
        chat = Chat.objects.create(name="Str Chat Long", is_group=True)
        long_content = "x" * 80
        message = Message.objects.create(
            sender=test_user, chat=chat, content=long_content
        )
        preview = long_content[:50] + "..."
        assert str(message) == f"{test_user.username}: {preview}"

    def test_message_ordering_by_sent_at(self, test_user):
        """Newest messages come first."""
        chat = Chat.objects.create(name="Ordering Chat", is_group=True)
        older_message = Message.objects.create(
            sender=test_user, chat=chat, content="Older message"
        )
        newer_message = Message.objects.create(
            sender=test_user, chat=chat, content="Newer message"
        )
        messages = list(Message.objects.filter(chat=chat))
        assert messages[0] == newer_message
        assert messages[1] == older_message

    def test_is_private_flags(self, test_user):
        """is_private() follows chat type."""
        private_chat = Chat.objects.create(name="Private Chat", is_group=False)
        group_chat = Chat.objects.create(name="Group Chat", is_group=True)
        private_msg = Message.objects.create(
            sender=test_user, chat=private_chat, content="Private"
        )
        group_msg = Message.objects.create(
            sender=test_user, chat=group_chat, content="Group"
        )
        assert private_msg.is_private() is True
        assert group_msg.is_private() is False

    def test_get_chat_context_for_different_chat_types(self, test_user):
        """get_chat_context() for group and private chats."""
        group_chat = Chat.objects.create(name="Group Chat", is_group=True)
        private_chat = Chat.objects.create(name="Private Chat", is_group=False)
        group_msg = Message.objects.create(
            sender=test_user, chat=group_chat, content="Group"
        )
        private_msg = Message.objects.create(
            sender=test_user, chat=private_chat, content="Private"
        )
        group_ctx = group_msg.get_chat_context()
        assert group_ctx["type"] == "group"
        assert "name" in group_ctx
        private_ctx = private_msg.get_chat_context()
        assert private_ctx["type"] == "private"
        assert "name" in private_ctx
