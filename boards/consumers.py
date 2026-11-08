"""WebSocket consumer for board sync. The editor is not in this module."""

from __future__ import annotations

import json
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from chat.group_services import get_participant

from .broadcast import board_group_name, board_user_group_name
from .models import Board
from .ops import apply_ops, live_snapshot
from .presence import presence_join, presence_leave
from .protocol import (
    ProtocolError,
    parse_client_op_id,
    parse_object_id,
    sanitize_transient_patch,
)


def _reject_nonfinite(_name):
    raise ValueError("Non-finite JSON numbers are not allowed.")


class RateWindow:
    """Count hits in a rolling one-second window for this socket."""

    def __init__(self, limit):
        self.limit = int(limit)
        self.times = []

    def allow(self):
        now = time.monotonic()
        cutoff = now - 1.0
        self.times = [stamp for stamp in self.times if stamp > cutoff]
        if len(self.times) >= self.limit:
            return False
        self.times.append(now)
        return True


class BoardConsumer(AsyncWebsocketConsumer):
    """Session-authenticated board channel."""

    async def connect(self):
        self.user = self.scope["user"]
        self.board_id = self.scope["url_route"]["kwargs"]["board_id"]
        self.chat_id = None
        self.board_group = None
        self.user_group = None
        self.can_edit = False
        self._ops_rate = RateWindow(settings.BOARDS_OPS_PER_SECOND)
        self._cursor_rate = RateWindow(settings.BOARDS_TRANSIENT_PER_SECOND)
        self._transient_rate = RateWindow(settings.BOARDS_TRANSIENT_PER_SECOND)

        if isinstance(self.user, AnonymousUser):
            await self.close(code=4401)
            return
        access = await self._load_access()
        if access is None:
            await self.close(code=4403)
            return
        self.chat_id = str(access["chat_id"])
        self.can_edit = access["can_edit"]
        self.board_group = board_group_name(self.board_id)
        self.user_group = board_user_group_name(self.user.pk)
        await self.channel_layer.group_add(self.board_group, self.channel_name)
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.accept()
        users, first = await self._presence_join()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "init",
                    "seq": access["seq"],
                    "objects": access["objects"],
                    "users": users,
                }
            )
        )
        if first:
            await self.channel_layer.group_send(
                self.board_group,
                {
                    "type": "board.presence",
                    "payload": {
                        "type": "presence",
                        "action": "join",
                        "user": {"id": str(self.user.pk), "username": self.user.username},
                    },
                },
            )

    async def disconnect(self, close_code):
        if self.board_group:
            _users, last = await self._presence_leave()
            if last and getattr(self, "user", None) is not None:
                await self.channel_layer.group_send(
                    self.board_group,
                    {
                        "type": "board.presence",
                        "payload": {
                            "type": "presence",
                            "action": "leave",
                            "user": {
                                "id": str(self.user.pk),
                                "username": self.user.username,
                            },
                        },
                    },
                )
            await self.channel_layer.group_discard(self.board_group, self.channel_name)
        if self.user_group:
            await self.channel_layer.group_discard(self.user_group, self.channel_name)

    async def receive(self, text_data):
        raw = text_data if isinstance(text_data, str) else text_data.decode("utf-8")
        if len(raw.encode("utf-8")) > int(settings.BOARDS_MAX_MESSAGE_BYTES):
            await self._error("too_large", "Message is too large.")
            return
        try:
            data = json.loads(raw, parse_constant=_reject_nonfinite)
        except (TypeError, ValueError):
            await self._error("bad_payload", "Message must be JSON.")
            return
        if not isinstance(data, dict):
            await self._error("bad_payload", "Message must be an object.")
            return
        kind = data.get("type")
        if kind == "ops":
            if not await self._still_member():
                await self.close(code=4403)
                return
            await self._handle_ops(data)
        elif kind == "cursor":
            await self._handle_cursor(data)
        elif kind == "transient":
            await self._handle_transient(data)
        else:
            await self._error("bad_payload", "Unknown message type.")

    async def board_ops(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def board_cursor(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def board_transient(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def board_presence(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def board_force_close(self, event):
        chat_id = event.get("chat_id")
        if chat_id and self.chat_id and str(chat_id) != str(self.chat_id):
            return
        await self.close(code=4403)

    async def _handle_ops(self, data):
        if not self._ops_rate.allow():
            await self._error(
                "rate_limited",
                "Too many ops.",
                client_op_id=data.get("client_op_id"),
            )
            return
        try:
            client_op_id = parse_client_op_id(data.get("client_op_id"))
            board, applied = await self._apply_ops(data.get("ops"))
        except ProtocolError as exc:
            await self._error(exc.code, exc.detail, client_op_id=data.get("client_op_id"))
            return
        except PermissionError:
            await self.close(code=4403)
            return
        except Board.DoesNotExist:
            await self.close(code=4403)
            return
        payload = {
            "type": "ops",
            "seq": board.seq,
            "user": {"id": str(self.user.pk), "username": self.user.username},
            "ops": applied,
            "client_op_id": client_op_id,
        }
        await self.channel_layer.group_send(
            self.board_group,
            {"type": "board.ops", "payload": payload},
        )

    async def _handle_cursor(self, data):
        if not self._cursor_rate.allow():
            await self._error("rate_limited", "Too many cursor updates.")
            return
        patch = sanitize_transient_patch({"x": data.get("x"), "y": data.get("y")})
        if "x" not in patch or "y" not in patch:
            await self._error("invalid_object", "Cursor needs x and y.")
            return
        await self.channel_layer.group_send(
            self.board_group,
            {
                "type": "board.cursor",
                "payload": {
                    "type": "cursor",
                    "user": {"id": str(self.user.pk), "username": self.user.username},
                    "x": patch["x"],
                    "y": patch["y"],
                },
            },
        )

    async def _handle_transient(self, data):
        if not self.can_edit:
            await self._error("locked", "This board is locked.")
            return
        if not self._transient_rate.allow():
            await self._error("rate_limited", "Too many transient updates.")
            return
        try:
            oid = parse_object_id(data.get("id"))
            patch = sanitize_transient_patch(data.get("patch") or {})
        except ProtocolError as exc:
            await self._error(exc.code, exc.detail)
            return
        await self.channel_layer.group_send(
            self.board_group,
            {
                "type": "board.transient",
                "payload": {
                    "type": "transient",
                    "id": str(oid),
                    "patch": patch,
                    "user": {"id": str(self.user.pk), "username": self.user.username},
                },
            },
        )

    async def _error(self, code, detail, client_op_id=None):
        payload = {"type": "error", "code": code, "detail": detail}
        if client_op_id is not None:
            payload["client_op_id"] = client_op_id
        await self.send(text_data=json.dumps(payload))

    @database_sync_to_async
    def _load_access(self):
        board = (
            Board.objects.select_related("chat")
            .filter(pk=self.board_id)
            .first()
        )
        if board is None or not board.chat.is_group:
            return None
        participant = get_participant(board.chat, self.user)
        if participant is None:
            return None
        return {
            "chat_id": board.chat_id,
            "seq": board.seq,
            "objects": live_snapshot(board),
            "can_edit": (not board.is_locked) or participant.is_admin(),
        }

    @database_sync_to_async
    def _still_member(self):
        board = Board.objects.select_related("chat").filter(pk=self.board_id).first()
        if board is None:
            return False
        return get_participant(board.chat, self.user) is not None

    @database_sync_to_async
    def _apply_ops(self, ops):
        return apply_ops(self.board_id, self.user, ops)

    @database_sync_to_async
    def _presence_join(self):
        return presence_join(self.board_id, self.user, self.channel_name)

    @database_sync_to_async
    def _presence_leave(self):
        return presence_leave(self.board_id, self.user, self.channel_name)
