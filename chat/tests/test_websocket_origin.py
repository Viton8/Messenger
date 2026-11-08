"""Origin checks on the shared WebSocket ASGI stack."""

import pytest
from asgiref.sync import async_to_sync
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator
from django.test.utils import override_settings

from boards.services import create_board
from chat.group_services import create_group
from config.routing import websocket_application


class _ForceUser:
    """Put a user on the scope after Origin validation."""

    def __init__(self, inner, user):
        self.inner = inner
        self.user = user

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = self.user
        return await self.inner(scope, receive, send)


def _stack(user):
    return AllowedHostsOriginValidator(_ForceUser(websocket_application, user))


async def _connect(app, path, origin):
    communicator = WebsocketCommunicator(
        app,
        path,
        headers=[(b"origin", origin)],
    )
    connected, code = await communicator.connect()
    return communicator, connected, code


@pytest.mark.django_db(transaction=True)
class TestWebsocketOrigin:
    """Foreign Origin is refused; a matching Origin reaches the consumer."""

    @override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1"])
    def test_foreign_origin_is_rejected_for_chat_and_boards(self, test_user):
        """An Origin host outside ALLOWED_HOSTS does not connect."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        app = _stack(test_user)

        async def scenario():
            for path in (
                f"/ws/chat/{chat.pk}/",
                f"/ws/boards/{board.pk}/",
            ):
                communicator, connected, _code = await _connect(
                    app, path, b"https://evil.example"
                )
                assert connected is False
                await communicator.wait()

        async_to_sync(scenario)()

    @override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1"])
    def test_allowed_origin_is_accepted_for_chat_and_boards(self, test_user):
        """localhost Origin is accepted for both channels."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        app = _stack(test_user)

        async def scenario():
            chat_ws, chat_ok, _ = await _connect(
                app, f"/ws/chat/{chat.pk}/", b"http://localhost"
            )
            assert chat_ok is True
            await chat_ws.disconnect()
            board_ws, board_ok, _ = await _connect(
                app, f"/ws/boards/{board.pk}/", b"http://localhost"
            )
            assert board_ok is True
            await board_ws.disconnect()

        async_to_sync(scenario)()
