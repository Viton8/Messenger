"""Server-rendered board page (collaborative canvas editor)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from chat.group_services import get_participant

from .models import Board


@login_required
def board_page(request, board_id):
    """Show one board to a group member with the collaborative editor."""
    board = get_object_or_404(
        Board.objects.select_related("chat"),
        pk=board_id,
    )
    chat = board.chat
    if not chat.is_group or not chat.has_participant(request.user):
        messages.error(request, "You are not a member of this chat.")
        return redirect("chat:inbox")
    participant = get_participant(chat, request.user)
    read_only = board.is_locked and not (participant and participant.is_admin())
    return render(
        request,
        "boards/board.html",
        {
            "board": board,
            "chat": chat,
            "back_url": reverse("chat:room", kwargs={"chat_id": chat.pk}),
            "read_only": read_only,
        },
    )
