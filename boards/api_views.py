"""REST views for group board metadata."""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.group_services import require_participant
from chat.models import Chat

from .models import Board
from .serializers import BoardCreateSerializer, BoardPatchSerializer
from .services import create_board, delete_board, list_boards, update_board


def _http_error(exc):
    """Map service errors to DRF responses."""
    if isinstance(exc, PermissionError):
        raise PermissionDenied(str(exc)) from exc
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _board_url(board):
    """Relative page path for one board."""
    return f"/boards/{board.pk}/"


def _board_payload(board):
    """JSON body for list and detail responses."""
    creator = board.created_by
    return {
        "id": str(board.pk),
        "chat_id": str(board.chat_id),
        "title": board.title,
        "created_by": {
            "id": str(creator.pk),
            "username": creator.username,
        },
        "created_at": board.created_at.isoformat(),
        "updated_at": board.updated_at.isoformat(),
        "is_locked": board.is_locked,
        "seq": board.seq,
        "url": _board_url(board),
    }


class GroupBoardListAPIView(APIView):
    """List or create boards in a group."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, chat_id):
        """Return boards for a group member."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            boards = list_boards(chat, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response([_board_payload(board) for board in boards])

    def post(self, request, chat_id):
        """Create a board. Any member may call this."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        ser = BoardCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            board = create_board(chat, request.user, ser.validated_data["title"])
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_board_payload(board), status=status.HTTP_201_CREATED)


class GroupBoardDetailAPIView(APIView):
    """Retrieve, patch, or delete one board."""

    permission_classes = [permissions.IsAuthenticated]

    def _load(self, request, chat_id, board_id):
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            require_participant(chat, request.user)
        except PermissionError as exc:
            return _http_error(exc)
        board = get_object_or_404(
            Board.objects.select_related("created_by", "chat"),
            pk=board_id,
            chat=chat,
        )
        return chat, board

    def get(self, request, chat_id, board_id):
        """Return one board for a member."""
        loaded = self._load(request, chat_id, board_id)
        if isinstance(loaded, Response):
            return loaded
        _chat, board = loaded
        return Response(_board_payload(board))

    def patch(self, request, chat_id, board_id):
        """Change title and/or lock with field-level rights."""
        loaded = self._load(request, chat_id, board_id)
        if isinstance(loaded, Response):
            return loaded
        _chat, board = loaded
        ser = BoardPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            board = update_board(
                board,
                request.user,
                title=ser.validated_data.get("title"),
                is_locked=ser.validated_data.get("is_locked"),
            )
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_board_payload(board))

    def delete(self, request, chat_id, board_id):
        """Delete the board. Creator or admin."""
        loaded = self._load(request, chat_id, board_id)
        if isinstance(loaded, Response):
            return loaded
        _chat, board = loaded
        try:
            delete_board(board, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
