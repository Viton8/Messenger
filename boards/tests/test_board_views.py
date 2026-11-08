"""Tests for the board page and chat-room board card."""

import pytest
from django.urls import reverse

from boards.models import Board
from boards.services import create_board, delete_board
from chat.group_services import create_group
from chat.services import BOARD_DELETED_PLACEHOLDER


@pytest.mark.django_db
class TestBoardTemplateViews:
    """Session pages for opening a board and seeing the chat card."""

    def test_board_page_requires_login(self, client, test_user):
        """Anonymous visitors are sent to login."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        response = client.get(reverse("boards:board", kwargs={"board_id": board.pk}))
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_member_sees_fullscreen_canvas(self, client, test_user):
        """A member gets the title, back link, editor script, and toolbar."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        client.force_login(test_user)
        response = client.get(reverse("boards:board", kwargs={"board_id": board.pk}))
        assert response.status_code == 200
        html = response.content.decode()
        assert "Wall" in html
        assert "Back to chat" in html
        assert reverse("chat:room", kwargs={"chat_id": chat.pk}) in html
        assert "<canvas" in html
        assert 'id="board-canvas"' in html
        assert 'type="module"' in html
        assert "boards/js/main.js" in html
        assert 'data-board-toolbar' in html
        assert 'data-read-only="false"' in html
        assert "aria-label=\"Select (V)\"" in html

    def test_locked_board_shows_badge(self, client, test_user):
        """The locked flag is visible on the page."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        board.is_locked = True
        board.save(update_fields=["is_locked"])
        client.force_login(test_user)
        html = client.get(
            reverse("boards:board", kwargs={"board_id": board.pk})
        ).content.decode()
        assert "Locked" in html
        assert 'data-read-only="false"' in html

    def test_locked_board_is_read_only_for_member(self, client, test_user, second_user):
        """A locked board is read-only for a non-admin member."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        board.is_locked = True
        board.save(update_fields=["is_locked"])
        chat.add_participant(second_user, role="member")
        client.force_login(second_user)
        html = client.get(
            reverse("boards:board", kwargs={"board_id": board.pk})
        ).content.decode()
        assert 'data-read-only="true"' in html
        assert "Read only" in html

    def test_non_member_is_redirected(self, client, test_user, second_user):
        """An outsider is sent back to the inbox."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        client.force_login(second_user)
        response = client.get(reverse("boards:board", kwargs={"board_id": board.pk}))
        assert response.status_code == 302
        assert response.url == reverse("chat:inbox")

    def test_room_shows_open_board_card(self, client, test_user):
        """The group room renders a board card with Open board."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        assert "New board" in html
        assert "chat-board-card" in html
        assert "Open board" in html
        assert reverse("boards:board", kwargs={"board_id": board.pk}) in html
        assert "Wall" in html
        assert 'data-kind="board"' in html

    def test_deleted_board_card_hides_open_button(self, client, test_user):
        """After delete the room shows Board deleted without Open board."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        delete_board(board, test_user)
        client.force_login(test_user)
        html = client.get(reverse("chat:room", kwargs={"chat_id": chat.pk})).content.decode()
        assert BOARD_DELETED_PLACEHOLDER in html
        assert "Open board" not in html
        assert Board.objects.filter(chat=chat).count() == 0

    def test_missing_board_is_404(self, client, test_user):
        """Unknown board id is 404 for a signed-in user."""
        client.force_login(test_user)
        response = client.get(
            reverse(
                "boards:board",
                kwargs={"board_id": "00000000-0000-0000-0000-000000000001"},
            )
        )
        assert response.status_code == 404
