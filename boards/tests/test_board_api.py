"""Tests for board metadata REST rules."""

import pytest
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status

from boards.models import Board
from boards.services import create_board
from chat.group_services import create_group, set_member_role
from chat.models import Chat, Message
from chat.services import BOARD_DELETED_PLACEHOLDER


@pytest.mark.django_db
class TestBoardAPI:
    """Create, list, patch, lock, and delete boards in a group."""

    def _login(self, api_client, user):
        api_client.force_login(user)

    def _group(self, owner):
        return create_group(owner, "Desk")

    def _list_url(self, chat):
        return reverse("chat-group-boards", kwargs={"chat_id": chat.pk})

    def _detail_url(self, chat, board):
        return reverse(
            "chat-group-board-detail",
            kwargs={"chat_id": chat.pk, "board_id": board.pk},
        )

    def test_member_creates_and_lists(self, api_client, test_user, second_user):
        """Any member may POST a board and GET the list."""
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        self._login(api_client, second_user)
        created = api_client.post(self._list_url(chat), {"title": "  Sprint  "}, format="json")
        assert created.status_code == status.HTTP_201_CREATED
        assert created.data["title"] == "Sprint"
        assert created.data["created_by"]["username"] == second_user.username
        assert created.data["is_locked"] is False
        assert created.data["seq"] == 0
        assert created.data["url"] == f"/boards/{created.data['id']}/"
        listed = api_client.get(self._list_url(chat))
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.data) == 1
        board = Board.objects.get(pk=created.data["id"])
        card = Message.objects.get(chat=chat, kind=Message.KIND_BOARD, board=board)
        assert card.content == "Sprint"
        assert card.sender_id == second_user.pk

    def test_non_member_is_forbidden(self, api_client, test_user, second_user):
        """An outsider cannot list or create boards."""
        chat = self._group(test_user)
        self._login(api_client, second_user)
        listed = api_client.get(self._list_url(chat))
        created = api_client.post(self._list_url(chat), {"title": "Nope"}, format="json")
        assert listed.status_code == status.HTTP_403_FORBIDDEN
        assert created.status_code == status.HTTP_403_FORBIDDEN
        assert Board.objects.filter(chat=chat).count() == 0

    def test_direct_chat_boards_are_404(self, api_client, test_user, second_user):
        """Board routes only exist on group chats."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        self._login(api_client, test_user)
        response = api_client.get(self._list_url(chat))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unknown_group_is_404(self, api_client, test_user):
        """Missing group id is 404."""
        self._login(api_client, test_user)
        response = api_client.get(
            reverse(
                "chat-group-boards",
                kwargs={"chat_id": "00000000-0000-0000-0000-000000000001"},
            )
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_board_from_another_group_is_404(
        self, api_client, test_user, second_user
    ):
        """A board id from a different group does not leak."""
        first = self._group(test_user)
        other = create_group(second_user, "Other")
        board = create_board(other, second_user, "Secret")
        self._login(api_client, test_user)
        response = api_client.get(self._detail_url(first, board))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_empty_title_is_400(self, api_client, test_user):
        """Blank titles are rejected."""
        chat = self._group(test_user)
        self._login(api_client, test_user)
        response = api_client.post(self._list_url(chat), {"title": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Board.objects.filter(chat=chat).count() == 0

    def test_member_cannot_rename_or_delete_others_board(
        self, api_client, test_user, second_user
    ):
        """A non-creator member cannot PATCH title or DELETE another member's board."""
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")
        self._login(api_client, second_user)
        renamed = api_client.patch(
            self._detail_url(chat, board), {"title": "Stolen"}, format="json"
        )
        deleted = api_client.delete(self._detail_url(chat, board))
        assert renamed.status_code == status.HTTP_403_FORBIDDEN
        assert deleted.status_code == status.HTTP_403_FORBIDDEN
        board.refresh_from_db()
        assert board.title == "Wall"

    def test_creator_can_rename_and_delete(self, api_client, test_user, second_user):
        """The creator may PATCH title and DELETE while still a member."""
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        board = create_board(chat, second_user, "Wall")
        self._login(api_client, second_user)
        renamed = api_client.patch(
            self._detail_url(chat, board), {"title": "Renamed"}, format="json"
        )
        assert renamed.status_code == status.HTTP_200_OK
        assert renamed.data["title"] == "Renamed"
        removed = api_client.delete(self._detail_url(chat, board))
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        assert Board.objects.filter(pk=board.pk).exists() is False

    def test_admin_can_rename_and_delete_others(
        self, api_client, test_user, second_user
    ):
        """Admin or owner may change or remove another member's board."""
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        board = create_board(chat, second_user, "Wall")
        self._login(api_client, test_user)
        renamed = api_client.patch(
            self._detail_url(chat, board), {"title": "Ops"}, format="json"
        )
        assert renamed.status_code == status.HTTP_200_OK
        assert renamed.data["title"] == "Ops"
        removed = api_client.delete(self._detail_url(chat, board))
        assert removed.status_code == status.HTTP_204_NO_CONTENT

    def test_member_cannot_lock_even_own_board(
        self, api_client, test_user, second_user
    ):
        """Lock is admin-only. A creator member's lock PATCH is 403 and a no-op."""
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        board = create_board(chat, second_user, "Wall")
        self._login(api_client, second_user)
        locked = api_client.patch(
            self._detail_url(chat, board),
            {"title": "Still wall", "is_locked": True},
            format="json",
        )
        assert locked.status_code == status.HTTP_403_FORBIDDEN
        board.refresh_from_db()
        assert board.title == "Wall"
        assert board.is_locked is False

    def test_admin_can_lock(self, api_client, test_user, second_user, user_factory):
        """An admin may toggle is_locked."""
        lead = user_factory(username="helper")
        chat = self._group(test_user)
        chat.add_participant(second_user, role="member")
        chat.add_participant(lead, role="member")
        set_member_role(chat, test_user, lead, "admin")
        board = create_board(chat, second_user, "Wall")
        self._login(api_client, lead)
        locked = api_client.patch(
            self._detail_url(chat, board), {"is_locked": True}, format="json"
        )
        assert locked.status_code == status.HTTP_200_OK
        assert locked.data["is_locked"] is True

    @override_settings(BOARDS_MAX_PER_GROUP=2)
    def test_board_cap_rejects_the_next(self, api_client, test_user):
        """A full group cannot add another board."""
        chat = self._group(test_user)
        self._login(api_client, test_user)
        first = api_client.post(self._list_url(chat), {"title": "One"}, format="json")
        second = api_client.post(self._list_url(chat), {"title": "Two"}, format="json")
        third = api_client.post(self._list_url(chat), {"title": "Three"}, format="json")
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert third.status_code == status.HTTP_400_BAD_REQUEST
        assert "maximum" in str(third.data["detail"]).lower()
        assert Board.objects.filter(chat=chat).count() == 2

    def test_delete_marks_the_chat_card(self, api_client, test_user):
        """Deleting a board clears the FK and shows Board deleted."""
        chat = self._group(test_user)
        board = create_board(chat, test_user, "Wall")
        card = Message.objects.get(board=board)
        self._login(api_client, test_user)
        removed = api_client.delete(self._detail_url(chat, board))
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        card.refresh_from_db()
        assert Board.objects.filter(pk=board.pk).exists() is False
        assert card.kind == Message.KIND_BOARD
        assert card.board_id is None
        assert card.deleted_at is not None
        listed = api_client.get(reverse("chat-messages", kwargs={"chat_id": chat.pk}))
        found = next(row for row in listed.data if row["id"] == str(card.pk))
        assert found["deleted"] is True
        assert found["content"] == BOARD_DELETED_PLACEHOLDER
        assert found["board_id"] is None
        assert found["board_url"] is None

    def test_message_api_cannot_edit_or_delete_board_card(
        self, api_client, test_user
    ):
        """Board cards are not user-editable through the message endpoints."""
        chat = self._group(test_user)
        board = create_board(chat, test_user, "Wall")
        card = Message.objects.get(board=board)
        self._login(api_client, test_user)
        url = reverse(
            "chat-message-detail",
            kwargs={"chat_id": chat.pk, "message_id": card.pk},
        )
        patched = api_client.patch(url, {"content": "rewritten"}, format="json")
        deleted = api_client.delete(url)
        assert patched.status_code == status.HTTP_403_FORBIDDEN
        assert deleted.status_code == status.HTTP_403_FORBIDDEN
        card.refresh_from_db()
        assert card.deleted_at is None
        assert card.content == "Wall"
        assert Board.objects.filter(pk=board.pk).exists()
