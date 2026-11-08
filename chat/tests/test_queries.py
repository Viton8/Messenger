"""Tests for common query patterns on the Message model."""

import pytest

from chat.models import Chat, Message


@pytest.mark.django_db
class TestMessageQueries:
    """Typical query scenarios around Message objects."""

    @pytest.fixture(autouse=True)
    def set_up(self, test_user, second_user):
        """Prepare users and base chats for the query tests."""
        self.user1 = test_user
        self.user2 = second_user
        self.group_chat = Chat.objects.create(name="Group Chat", is_group=True)
        self.private_chat = Chat.objects.create(name="Private Chat", is_group=False)

    def test_get_group_messages(self):
        """Group messages are retrieved only from the group chat."""
        msg1 = Message.objects.create(sender=self.user1, chat=self.group_chat, content="1")
        msg2 = Message.objects.create(sender=self.user2, chat=self.group_chat, content="2")
        Message.objects.create(sender=self.user1, chat=self.private_chat, content="private")
        messages = list(Message.objects.filter(chat=self.group_chat).order_by("-sent_at"))
        assert len(messages) == 2
        assert messages[0] == msg2
        assert messages[1] == msg1

    def test_get_group_messages_limit(self):
        """Limiting group messages via slice returns expected count."""
        for i in range(5):
            Message.objects.create(
                sender=self.user1, chat=self.group_chat, content=f"Msg {i}"
            )
        messages = list(
            Message.objects.filter(chat=self.group_chat).order_by("-sent_at")[:3]
        )
        assert len(messages) == 3

    def test_get_group_messages_empty(self):
        """A group chat with no messages returns an empty result."""
        empty_chat = Chat.objects.create(name="Empty Group", is_group=True)
        messages = list(Message.objects.filter(chat=empty_chat).order_by("-sent_at"))
        assert len(messages) == 0

    def test_get_private_conversation(self):
        """Private conversation is isolated to its chat."""
        msg1 = Message.objects.create(sender=self.user1, chat=self.private_chat, content="Hi")
        msg2 = Message.objects.create(
            sender=self.user2, chat=self.private_chat, content="Hello"
        )
        other_private_chat = Chat.objects.create(name="Other Private", is_group=False)
        Message.objects.create(sender=self.user1, chat=self.group_chat, content="Group msg")
        Message.objects.create(
            sender=self.user1, chat=other_private_chat, content="To someone else"
        )
        messages = list(
            Message.objects.filter(chat=self.private_chat).order_by("-sent_at")
        )
        assert len(messages) == 2
        assert msg1 in messages
        assert msg2 in messages

    def test_get_private_conversation_order(self):
        """Private messages are ordered newest first inside a chat."""
        msg1 = Message.objects.create(
            sender=self.user1, chat=self.private_chat, content="First"
        )
        msg2 = Message.objects.create(
            sender=self.user2, chat=self.private_chat, content="Second"
        )
        messages = list(
            Message.objects.filter(chat=self.private_chat).order_by("-sent_at")
        )
        assert messages[0] == msg2
        assert messages[1] == msg1

    def test_get_private_conversation_limit(self):
        """Limiting private conversation size via slice."""
        for i in range(5):
            Message.objects.create(
                sender=self.user1, chat=self.private_chat, content=f"Msg {i}"
            )
        messages = list(
            Message.objects.filter(chat=self.private_chat).order_by("-sent_at")[:3]
        )
        assert len(messages) == 3

    def test_private_conversation_is_chat_specific(self):
        """Messages from another private chat do not appear in the original chat."""
        Message.objects.create(
            sender=self.user1, chat=self.private_chat, content="Original chat"
        )
        another_private_chat = Chat.objects.create(
            name="Another Private Chat", is_group=False
        )
        Message.objects.create(
            sender=self.user1,
            chat=another_private_chat,
            content="Another chat message",
        )
        messages_original = list(
            Message.objects.filter(chat=self.private_chat).order_by("-sent_at")
        )
        messages_other = list(
            Message.objects.filter(chat=another_private_chat).order_by("-sent_at")
        )
        assert len(messages_original) == 1
        assert len(messages_other) == 1
        assert messages_original[0].chat == self.private_chat
        assert messages_other[0].chat == another_private_chat
