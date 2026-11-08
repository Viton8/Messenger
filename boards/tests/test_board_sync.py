"""Board WebSocket protocol tests via WebsocketCommunicator."""

import uuid

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test.utils import override_settings

from boards.consumers import BoardConsumer
from boards.models import Board, BoardObject
from boards.services import create_board, delete_board
from chat.group_services import create_group, remove_member
from chat.models import ChatParticipant


def _oid():
    return str(uuid.uuid4())


async def _open(user, board):
    communicator = WebsocketCommunicator(
        BoardConsumer.as_asgi(),
        f"/ws/boards/{board.pk}/",
    )
    communicator.scope["user"] = user
    communicator.scope["url_route"] = {"kwargs": {"board_id": str(board.pk)}}
    connected, code = await communicator.connect()
    return communicator, connected, code


async def _open_ok(user, board):
    communicator, connected, code = await _open(user, board)
    assert connected, code
    init = await communicator.receive_json_from()
    assert init["type"] == "init"
    join = await communicator.receive_json_from()
    assert join["type"] == "presence"
    assert join["action"] == "join"
    return communicator, init


async def _until(communicator, kind, limit=12):
    for _ in range(limit):
        message = await communicator.receive_json_from()
        if message.get("type") == kind:
            return message
    raise AssertionError("did not receive %s" % kind)


async def _wait_close(communicator):
    for _ in range(12):
        event = await communicator.receive_output(timeout=2)
        if event["type"] == "websocket.close":
            return event
    raise AssertionError("socket did not close")


def _rect(oid, **extra):
    data = {"type": "rect", "x": 1, "y": 2, "width": 10, "height": 8}
    data.update(extra)
    return {"op": "add", "id": oid, "data": data}


@pytest.mark.django_db(transaction=True)
class TestBoardSync:
    """Connect, ops, cursors, limits, lock, and forced close."""

    def test_anonymous_is_4401(self, test_user):
        """Anonymous sockets are rejected with 4401."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, connected, code = await _open(AnonymousUser(), board)
            assert connected is False
            assert code == 4401

        async_to_sync(scenario)()

    def test_non_member_is_4403(self, test_user, second_user):
        """A signed-in outsider is rejected with 4403."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, connected, code = await _open(second_user, board)
            assert connected is False
            assert code == 4403

        async_to_sync(scenario)()

    def test_init_snapshot_is_empty(self, test_user):
        """A new board sends seq 0, no objects, and the caller in users."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, init = await _open_ok(test_user, board)
            assert init["seq"] == 0
            assert init["objects"] == []
            assert any(row["id"] == str(test_user.pk) for row in init["users"])
            await communicator.disconnect()

        async_to_sync(scenario)()

    def test_add_patch_remove_and_z(self, test_user):
        """Add, patch, reorder, remove; reconnect sees the live snapshot."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        first = _oid()
        second = _oid()

        async def scenario():
            communicator, _init = await _open_ok(test_user, board)
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "c1",
                    "ops": [_rect(first), _rect(second, x=40)],
                }
            )
            added = await _until(communicator, "ops")
            assert added["client_op_id"] == "c1"
            assert added["seq"] == 1
            assert [row["op"] for row in added["ops"]] == ["add", "add"]
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "c2",
                    "ops": [{"op": "patch", "id": first, "patch": {"fill": "#f00"}}],
                }
            )
            patched = await _until(communicator, "ops")
            assert patched["ops"][0]["patch"]["fill"] == "#f00"
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "c3",
                    "ops": [{"op": "z", "id": first, "index": 1}],
                }
            )
            await _until(communicator, "ops")
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "c4",
                    "ops": [{"op": "remove", "id": second}],
                }
            )
            await _until(communicator, "ops")
            await communicator.disconnect()

        async_to_sync(scenario)()
        board.refresh_from_db()
        assert board.seq == 4
        live = list(
            BoardObject.objects.filter(board=board, deleted=False).order_by("z", "id")
        )
        assert len(live) == 1
        assert str(live[0].id) == first
        assert live[0].data["fill"] == "#f00"

        async def reconnect():
            communicator, init = await _open_ok(test_user, board)
            assert init["seq"] == 4
            assert [row["id"] for row in init["objects"]] == [first]
            await communicator.disconnect()

        async_to_sync(reconnect)()

    def test_two_clients_see_ops_and_merged_patches(self, test_user, second_user):
        """Both sockets see ops; two field patches both stick."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")
        oid = _oid()

        async def scenario():
            alice, _ = await _open_ok(test_user, board)
            bob, _ = await _open_ok(second_user, board)
            await _until(alice, "presence")
            await alice.send_json_to(
                {"type": "ops", "client_op_id": "a1", "ops": [_rect(oid)]}
            )
            assert (await _until(alice, "ops"))["client_op_id"] == "a1"
            assert (await _until(bob, "ops"))["client_op_id"] == "a1"
            await alice.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "a2",
                    "ops": [{"op": "patch", "id": oid, "patch": {"fill": "#0f0"}}],
                }
            )
            await _until(alice, "ops")
            await _until(bob, "ops")
            await bob.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "b1",
                    "ops": [{"op": "patch", "id": oid, "patch": {"x": 50}}],
                }
            )
            await _until(alice, "ops")
            await _until(bob, "ops")
            await alice.disconnect()
            await bob.disconnect()

        async_to_sync(scenario)()
        row = BoardObject.objects.get(pk=oid)
        assert row.data["fill"] == "#0f0"
        assert row.data["x"] == 50
        assert row.data["width"] == 10

    def test_two_clients_see_cursors_and_transient(self, test_user, second_user):
        """Cursor and transient frames are fanned out, not stored."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")
        oid = _oid()

        async def scenario():
            alice, _ = await _open_ok(test_user, board)
            bob, _ = await _open_ok(second_user, board)
            await _until(alice, "presence")
            await alice.send_json_to(
                {"type": "ops", "client_op_id": "a1", "ops": [_rect(oid)]}
            )
            await _until(alice, "ops")
            await _until(bob, "ops")
            await alice.send_json_to({"type": "cursor", "x": 9, "y": 12})
            cursor = await _until(bob, "cursor")
            assert cursor["x"] == 9
            assert cursor["user"]["id"] == str(test_user.pk)
            await alice.send_json_to(
                {"type": "transient", "id": oid, "patch": {"x": 3, "y": 4}}
            )
            transient = await _until(bob, "transient")
            assert transient["id"] == oid
            assert transient["patch"]["x"] == 3
            await alice.disconnect()
            await bob.disconnect()

        async_to_sync(scenario)()
        row = BoardObject.objects.get(pk=oid)
        assert row.data["x"] == 1

    def test_unknown_type_and_long_text_are_rejected(self, test_user):
        """Unknown types and oversized text fail the whole ops message."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, _ = await _open_ok(test_user, board)
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "bad-type",
                    "ops": [{"op": "add", "id": _oid(), "data": {"type": "image"}}],
                }
            )
            error = await _until(communicator, "error")
            assert error["code"] == "invalid_type"
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "bad-text",
                    "ops": [
                        {
                            "op": "add",
                            "id": _oid(),
                            "data": {
                                "type": "textbox",
                                "x": 0,
                                "y": 0,
                                "width": 10,
                                "height": 10,
                                "text": "x" * 2001,
                            },
                        }
                    ],
                }
            )
            text_error = await _until(communicator, "error")
            assert text_error["code"] == "invalid_object"
            await communicator.disconnect()

        async_to_sync(scenario)()
        assert BoardObject.objects.filter(board=board).count() == 0
        board.refresh_from_db()
        assert board.seq == 0

    @override_settings(BOARDS_MAX_LIVE_OBJECTS=1)
    def test_live_object_cap(self, test_user):
        """A full board rejects another add."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, _ = await _open_ok(test_user, board)
            await communicator.send_json_to(
                {"type": "ops", "client_op_id": "one", "ops": [_rect(_oid())]}
            )
            await _until(communicator, "ops")
            await communicator.send_json_to(
                {"type": "ops", "client_op_id": "two", "ops": [_rect(_oid())]}
            )
            error = await _until(communicator, "error")
            assert error["code"] == "limit"
            await communicator.disconnect()

        async_to_sync(scenario)()
        assert BoardObject.objects.filter(board=board, deleted=False).count() == 1

    @override_settings(BOARDS_OPS_PER_SECOND=1)
    def test_ops_rate_limit(self, test_user):
        """A second ops frame in the same second is dropped."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, _ = await _open_ok(test_user, board)
            await communicator.send_json_to(
                {"type": "ops", "client_op_id": "one", "ops": [_rect(_oid())]}
            )
            await _until(communicator, "ops")
            await communicator.send_json_to(
                {"type": "ops", "client_op_id": "two", "ops": [_rect(_oid())]}
            )
            error = await _until(communicator, "error")
            assert error["code"] == "rate_limited"
            await communicator.disconnect()

        async_to_sync(scenario)()
        board.refresh_from_db()
        assert board.seq == 1

    def test_locked_board_blocks_member_ops_not_cursors(self, test_user, second_user):
        """Members cannot ops a locked board; cursors still fan out. Admin can ops."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")
        board.is_locked = True
        board.save(update_fields=["is_locked"])

        async def scenario():
            owner, _ = await _open_ok(test_user, board)
            member, _ = await _open_ok(second_user, board)
            await _until(owner, "presence")
            await member.send_json_to(
                {"type": "ops", "client_op_id": "m1", "ops": [_rect(_oid())]}
            )
            error = await _until(member, "error")
            assert error["code"] == "locked"
            await member.send_json_to({"type": "cursor", "x": 1, "y": 2})
            cursor = await _until(owner, "cursor")
            assert cursor["user"]["id"] == str(second_user.pk)
            oid = _oid()
            await member.send_json_to(
                {"type": "transient", "id": oid, "patch": {"x": 3, "y": 4}}
            )
            locked_transient = await _until(member, "error")
            assert locked_transient["code"] == "locked"
            await owner.send_json_to(
                {"type": "transient", "id": oid, "patch": {"x": 5, "y": 6}}
            )
            transient = await _until(member, "transient")
            assert transient["patch"]["x"] == 5
            await owner.send_json_to(
                {"type": "ops", "client_op_id": "o1", "ops": [_rect(_oid())]}
            )
            added = await _until(owner, "ops")
            assert added["seq"] == 1
            await owner.disconnect()
            await member.disconnect()

        async_to_sync(scenario)()
        assert BoardObject.objects.filter(board=board, deleted=False).count() == 1

    def test_remove_member_closes_their_board_socket(self, test_user, second_user):
        """Kick closes the target's board WebSocket with 4403."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            owner, _ = await _open_ok(test_user, board)
            member, _ = await _open_ok(second_user, board)
            await _until(owner, "presence")
            await database_sync_to_async(remove_member)(chat, test_user, second_user)
            closed = await _wait_close(member)
            assert closed.get("code") == 4403
            await owner.disconnect()

        async_to_sync(scenario)()

    def test_delete_board_closes_all_sockets(self, test_user, second_user):
        """Deleting the board closes every connected socket."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            owner, _ = await _open_ok(test_user, board)
            member, _ = await _open_ok(second_user, board)
            await _until(owner, "presence")
            await database_sync_to_async(delete_board)(board, test_user)
            assert (await _wait_close(owner)).get("code") == 4403
            assert (await _wait_close(member)).get("code") == 4403

        async_to_sync(scenario)()
        assert Board.objects.filter(pk=board.pk).exists() is False

    def test_nonfinite_json_is_rejected(self, test_user):
        """NaN in the JSON text is bad_payload, not a drawn object."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")
        oid = _oid()

        async def scenario():
            communicator, _ = await _open_ok(test_user, board)
            await communicator.send_to(
                text_data=(
                    '{"type":"ops","client_op_id":"n1","ops":[{"op":"add","id":"%s",'
                    '"data":{"type":"rect","x":NaN,"y":1,"width":1,"height":1}}]}'
                    % oid
                )
            )
            error = await _until(communicator, "error")
            assert error["code"] == "bad_payload"
            await communicator.disconnect()

        async_to_sync(scenario)()
        assert BoardObject.objects.filter(pk=oid).exists() is False

    @override_settings(BOARDS_MAX_OPS_PER_MESSAGE=2)
    def test_too_many_ops_in_one_message(self, test_user):
        """A frame with more ops than the limit is refused and seq stays put."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            communicator, _ = await _open_ok(test_user, board)
            await communicator.send_json_to(
                {
                    "type": "ops",
                    "client_op_id": "many",
                    "ops": [_rect(_oid()), _rect(_oid()), _rect(_oid())],
                }
            )
            error = await _until(communicator, "error")
            assert error["code"] == "too_many_ops"
            await communicator.disconnect()

        async_to_sync(scenario)()
        board.refresh_from_db()
        assert board.seq == 0

    def test_duplicate_id_on_another_board(self, test_user):
        """The same object UUID cannot live on two boards."""
        chat = create_group(test_user, "Desk")
        first = create_board(chat, test_user, "One")
        second = create_board(chat, test_user, "Two")
        oid = _oid()

        async def scenario():
            a, _ = await _open_ok(test_user, first)
            b, _ = await _open_ok(test_user, second)
            await a.send_json_to(
                {"type": "ops", "client_op_id": "a1", "ops": [_rect(oid)]}
            )
            await _until(a, "ops")
            await b.send_json_to(
                {"type": "ops", "client_op_id": "b1", "ops": [_rect(oid)]}
            )
            error = await _until(b, "error")
            assert error["code"] == "duplicate_id"
            await a.disconnect()
            await b.disconnect()

        async_to_sync(scenario)()
        assert BoardObject.objects.filter(pk=oid, board=first).count() == 1
        assert BoardObject.objects.filter(pk=oid, board=second).count() == 0

    def test_removed_member_cannot_send_ops(self, test_user, second_user):
        """Ops after a quiet kick close the socket and do not write objects."""
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        board = create_board(chat, test_user, "Wall")
        oid = _oid()

        async def drop_row():
            await database_sync_to_async(
                lambda: ChatParticipant.objects.filter(
                    chat=chat, user=second_user
                ).delete()
            )()

        async def scenario():
            owner, _ = await _open_ok(test_user, board)
            member, _ = await _open_ok(second_user, board)
            await _until(owner, "presence")
            await drop_row()
            await member.send_json_to(
                {"type": "ops", "client_op_id": "k1", "ops": [_rect(oid)]}
            )
            closed = await _wait_close(member)
            assert closed.get("code") == 4403
            await owner.disconnect()

        async_to_sync(scenario)()
        board.refresh_from_db()
        assert board.seq == 0
        assert BoardObject.objects.filter(pk=oid).exists() is False

    def test_two_tabs_share_one_presence_row(self, test_user):
        """A second tab does not duplicate the user; leave waits for the last tab."""
        chat = create_group(test_user, "Desk")
        board = create_board(chat, test_user, "Wall")

        async def scenario():
            first, init1 = await _open_ok(test_user, board)
            assert [row["id"] for row in init1["users"]] == [str(test_user.pk)]
            second, connected, _code = await _open(test_user, board)
            assert connected
            init2 = await second.receive_json_from()
            assert init2["type"] == "init"
            assert [row["id"] for row in init2["users"]] == [str(test_user.pk)]
            assert await first.receive_nothing(timeout=0.3)
            await first.disconnect()
            assert await second.receive_nothing(timeout=0.3)
            await second.disconnect()

        async_to_sync(scenario)()
