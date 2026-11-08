"""Apply a batch of board ops in one locked transaction."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from chat.group_services import get_participant

from .models import Board, BoardObject
from .protocol import (
    ProtocolError,
    extract_type,
    parse_object_id,
    sanitize_properties,
)


def object_public(row):
    """JSON for one live object in init/snapshots."""
    return {
        "id": str(row.id),
        "type": row.type,
        "z": row.z,
        "data": row.data,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": str(row.updated_by_id) if row.updated_by_id else None,
    }


def live_snapshot(board):
    """Live objects in z order."""
    rows = BoardObject.objects.filter(board=board, deleted=False).order_by("z", "id")
    return [object_public(row) for row in rows]


def apply_ops(board_id, user, ops):
    """Lock the board, apply ``ops``, increment seq once.

    Returns:
        tuple[Board, list]: The board (with new seq) and sanitized ops.

    Raises:
        ProtocolError: Validation, lock, or limit failure.
        Board.DoesNotExist: Unknown board.
        PermissionError: Caller is not a member.
    """
    if not isinstance(ops, list) or not ops:
        raise ProtocolError("bad_payload", "ops must be a non-empty list.")
    with transaction.atomic():
        board = (
            Board.objects.select_for_update()
            .select_related("chat")
            .get(pk=board_id)
        )
        participant = get_participant(board.chat, user)
        if participant is None:
            raise PermissionError("You are not a member of this chat.")
        if board.is_locked and not participant.is_admin():
            raise ProtocolError("locked", "This board is locked.")
        applied = []
        for raw in ops:
            applied.append(_apply_one(board, user, raw))
        board.seq = int(board.seq) + 1
        board.save(update_fields=["seq"])
        return board, applied


def _apply_one(board, user, raw):
    if not isinstance(raw, dict):
        raise ProtocolError("bad_payload", "Each op must be an object.")
    kind = raw.get("op")
    if kind == "add":
        return _add(board, user, raw)
    if kind == "patch":
        return _patch(board, user, raw)
    if kind == "remove":
        return _remove(board, user, raw)
    if kind == "z":
        return _reorder(board, user, raw)
    raise ProtocolError("bad_payload", "Unknown op.")


def _live(board):
    return BoardObject.objects.filter(board=board, deleted=False)


def _next_z(board):
    current = _live(board).aggregate(top=Max("z"))["top"]
    if current is None:
        return 0
    return int(current) + 1


def _add(board, user, raw):
    oid = parse_object_id(raw.get("id"))
    obj_type = extract_type(raw)
    payload = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    data = sanitize_properties(obj_type, payload, partial=False)
    existing = BoardObject.objects.filter(pk=oid, board=board).first()
    if existing is not None and not existing.deleted:
        raise ProtocolError("duplicate_id", "That object already exists.")
    live_count = _live(board).count()
    if existing is None or existing.deleted:
        if live_count >= int(settings.BOARDS_MAX_LIVE_OBJECTS):
            raise ProtocolError("limit", "This board is full.")
    z = _next_z(board)
    if existing is None:
        BoardObject.objects.create(
            id=oid,
            board=board,
            type=obj_type,
            data=data,
            z=z,
            deleted=False,
            updated_by=user,
        )
    else:
        existing.type = obj_type
        existing.data = data
        existing.z = z
        existing.deleted = False
        existing.updated_by = user
        existing.save()
    return {"op": "add", "id": str(oid), "type": obj_type, "data": data, "z": z}


def _get_live(board, oid):
    row = BoardObject.objects.filter(pk=oid, board=board).first()
    if row is None or row.deleted:
        raise ProtocolError("not_found", "Object not found.")
    return row


def _patch(board, user, raw):
    oid = parse_object_id(raw.get("id"))
    row = _get_live(board, oid)
    patch = raw.get("patch")
    cleaned = sanitize_properties(row.type, patch if isinstance(patch, dict) else {}, partial=True)
    merged = dict(row.data or {})
    merged.update(cleaned)
    row.data = merged
    row.updated_by = user
    row.save(update_fields=["data", "updated_by", "updated_at"])
    return {"op": "patch", "id": str(oid), "patch": cleaned}


def _remove(board, user, raw):
    oid = parse_object_id(raw.get("id"))
    row = _get_live(board, oid)
    row.deleted = True
    row.updated_by = user
    row.save(update_fields=["deleted", "updated_by", "updated_at"])
    return {"op": "remove", "id": str(oid)}


def _reorder(board, user, raw):
    oid = parse_object_id(raw.get("id"))
    row = _get_live(board, oid)
    try:
        index = int(raw.get("index"))
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid_object", "z index must be an integer.") from exc
    live = list(_live(board).order_by("z", "id"))
    if index < 0 or index >= len(live):
        raise ProtocolError("invalid_object", "z index is out of range.")
    live = [item for item in live if item.pk != row.pk]
    live.insert(index, row)
    for z, item in enumerate(live):
        if item.z != z or item.pk == row.pk:
            item.z = z
            item.updated_by = user
            item.save(update_fields=["z", "updated_by", "updated_at"])
    return {"op": "z", "id": str(oid), "index": index}
