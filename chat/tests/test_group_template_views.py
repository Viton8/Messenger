"""Tests for new-group, join-by-token, and the group room panel."""

import pytest
from django.urls import reverse
from django.utils import timezone

from chat.group_services import create_group, rotate_invite
from chat.models import Chat, ChatParticipant, Message
from chat.services import DELETED_PLACEHOLDER


@pytest.mark.django_db
class TestGroupTemplateViews:
    """Session pages for creating a group, joining, and moderating in the room."""

    def test_inbox_links_to_new_group(self, client, test_user):
        """The chat list offers New group next to New direct message."""
        client.force_login(test_user)
        html = client.get(reverse("chat:inbox")).content.decode()
        assert reverse("chat:start_group") in html
        assert "New group" in html

    def test_start_group_creates_and_opens_room(self, client, test_user):
        """POST name redirects to the new group room as owner."""
        client.force_login(test_user)
        response = client.post(
            reverse("chat:start_group"),
            {"name": "Ops desk", "description": "On-call", "avatar_url": ""},
        )
        chat = Chat.objects.get(is_group=True, name="Ops desk")
        assert response.status_code == 302
        assert response.url == reverse("chat:room", kwargs={"chat_id": chat.pk})
        assert ChatParticipant.objects.get(chat=chat, user=test_user).role == "owner"

    def test_start_group_rejects_blank_name(self, client, test_user):
        """Empty name stays on the form."""
        client.force_login(test_user)
        response = client.post(reverse("chat:start_group"), {"name": "   "})
        assert response.status_code == 200
        assert Chat.objects.filter(is_group=True).count() == 0
        assert "required" in response.content.decode().lower() or "name" in response.content.decode().lower()

    def test_join_page_shows_name_and_post_adds_member(
        self, client, test_user, second_user
    ):
        """GET join shows the group; POST with a session creates membership."""
        chat = create_group(test_user, "Ops desk")
        token = rotate_invite(chat, test_user)
        client.force_login(second_user)
        page = client.get(reverse("chat:join_group", kwargs={"token": token}))
        assert page.status_code == 200
        html = page.content.decode()
        assert "Ops desk" in html
        assert "Join group" in html
        joined = client.post(reverse("chat:join_group", kwargs={"token": token}))
        assert joined.status_code == 302
        assert joined.url == reverse("chat:room", kwargs={"chat_id": chat.pk})
        assert ChatParticipant.objects.filter(chat=chat, user=second_user).exists()

    def test_revoked_invite_page_is_404(self, client, test_user, second_user):
        """A revoked token does not show a join button."""
        chat = create_group(test_user, "Ops desk")
        token = rotate_invite(chat, test_user)
        chat.invite_token = None
        chat.save(update_fields=["invite_token"])
        client.force_login(second_user)
        response = client.get(reverse("chat:join_group", kwargs={"token": token}))
        assert response.status_code == 404
        assert "Invite not valid" in response.content.decode()

    def test_group_room_panel_and_always_visible_names(
        self, client, test_user, second_user
    ):
        """Owner sees manage controls; sender names stay in the markup."""
        chat = create_group(test_user, "Ops desk")
        chat.add_participant(second_user, role="member")
        line = Message.objects.create(sender=second_user, chat=chat, content="hello-group")
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        assert 'data-is-group="1"' in html
        assert 'data-can-moderate="1"' in html
        assert 'id="chat-group-panel"' in html
        assert "Add by username" in html
        assert "Create invite link" in html
        assert "Leave group" in html
        block = html.split(f'data-message-id="{line.pk}"', 1)[1]
        meta = block.split("hello-group", 1)[0]
        assert second_user.username in meta
        assert "visually-hidden" not in meta

    def test_member_room_hides_manage_controls(self, client, test_user, second_user):
        """A member can leave but cannot add, invite, or promote."""
        chat = create_group(test_user, "Ops desk")
        chat.add_participant(second_user, role="member")
        client.force_login(second_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        assert 'data-can-moderate="0"' in html
        assert "Leave group" in html
        assert "Add by username" not in html
        assert "Create invite link" not in html
        assert "Make admin" not in html

    def test_own_message_has_edit_and_delete(self, client, test_user, second_user):
        """The sender sees Edit and Delete; a peer in a DM does not see Delete."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        mine = Message.objects.create(sender=test_user, chat=chat, content="my-line")
        theirs = Message.objects.create(sender=second_user, chat=chat, content="their-line")
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        mine_block = html.split(f'data-message-id="{mine.pk}"', 1)[1]
        mine_block = mine_block.split("data-message-id=", 1)[0]
        assert 'data-msg-action="edit"' in mine_block
        assert 'data-msg-action="delete"' in mine_block
        theirs_block = html.split(f'data-message-id="{theirs.pk}"', 1)[1]
        theirs_block = theirs_block.split("data-message-id=", 1)[0] if "data-message-id=" in theirs_block else theirs_block
        assert 'data-msg-action="edit"' not in theirs_block
        assert 'data-msg-action="delete"' not in theirs_block

    def test_group_admin_can_delete_others_line(self, client, test_user, second_user):
        """Group admin markup includes Delete on another member's user line."""
        chat = create_group(test_user, "Ops desk")
        chat.add_participant(second_user, role="member")
        theirs = Message.objects.create(sender=second_user, chat=chat, content="peer-line")
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        block = html.split(f'data-message-id="{theirs.pk}"', 1)[1]
        assert 'data-msg-action="delete"' in block
        assert 'data-msg-action="edit"' not in block.split("data-message-id=", 1)[0]

    def test_deleted_message_shows_placeholder_without_actions(
        self, client, test_user, second_user
    ):
        """Soft-deleted lines render the placeholder and no edit/delete buttons."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(sender=test_user, chat=chat, content="gone-now")
        message.deleted_at = timezone.now()
        message.save(update_fields=["deleted_at"])
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        assert DELETED_PLACEHOLDER in html
        assert "gone-now" not in html
        block = html.split(f'data-message-id="{message.pk}"', 1)[1]
        assert 'data-msg-action="edit"' not in block.split("id=\"chat-form\"", 1)[0]
        assert 'data-msg-action="delete"' not in block.split("id=\"chat-form\"", 1)[0]

    def test_already_member_join_redirects_to_room(
        self, client, test_user, second_user
    ):
        """Opening a valid invite while already a member skips the form."""
        chat = create_group(test_user, "Ops desk")
        token = rotate_invite(chat, test_user)
        chat.add_participant(second_user, role="member")
        client.force_login(second_user)
        response = client.get(reverse("chat:join_group", kwargs={"token": token}))
        assert response.status_code == 302
        assert response.url == reverse("chat:room", kwargs={"chat_id": chat.pk})
