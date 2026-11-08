"""Server-rendered views for chat (same behaviour as the REST API layer)."""

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ChatMessageForm, StartDirectChatForm, StartGroupChatForm
from .group_services import (
    can_delete_message,
    can_edit_message,
    create_group,
    get_participant,
    join_by_token,
)
from .models import Chat, ChatParticipant, Message
from .services import (
    BOARD_DELETED_PLACEHOLDER,
    DELETED_PLACEHOLDER,
    HISTORY_PAGE,
    assert_can_send_message,
    broadcast_chat_message,
    chat_folder,
    chat_list_params,
    chat_querystring,
    chat_title,
    format_chat_time,
    message_page,
    preview_text,
    unread_badge_label,
    visible_chats,
)

logger = logging.getLogger(__name__)

User = get_user_model()


_FOLDER_LABELS = {
    "direct": "Direct",
    "group": "Group",
}


@login_required
def chat_inbox(request):
    """Render the chat inbox for the signed-in user.

    The list uses the same folder and sort rules as the JSON list. Name search
    stays in the query string and is applied in the browser.

    Args:
        request (HttpRequest): Current request; ``request.user`` must be
            authenticated (enforced by ``@login_required``).

    Returns:
        HttpResponse: Rendered ``chat/home.html``.
    """
    return render(request, "chat/home.html", _chat_page_context(request))


def _chat_page_context(request, chat=None, form=None, messages_list=None, has_older=False, find=""):
    """Build the shared list-and-thread context.

    Args:
        request: Current request.
        chat: Open chat, or None on the inbox.
        form: Composer form when a chat is open.
        messages_list: Display rows for the open thread.
        has_older (bool): Whether an older page exists.
        find (str): In-thread search text.

    Returns:
        dict: Template context.
    """
    params = chat_list_params(request)
    # Search runs in the browser so typing does not reload the page. The
    # rendered rows still follow the tab, unread flag, and sort.
    listed = dict(params)
    listed["q"] = ""
    rows = []
    for item in visible_chats(request.user, listed):
        row = _inbox_row(item, request.user)
        row["href"] = _chat_href(item.pk, params)
        row["current"] = bool(chat and item.pk == chat.pk)
        rows.append(row)
    peer = chat.get_other_participant(request.user) if chat and chat.is_direct_message() else None
    membership = get_participant(chat, request.user) if chat and chat.is_group else None
    members = []
    if chat and chat.is_group:
        members = [
            {
                "id": row.user_id,
                "username": row.user.username,
                "role": row.role,
                "initials": row.user.display_initials(),
                "avatar_url": row.user.avatar_url or "",
                "profile_url": _profile_url(row.user),
            }
            for row in ChatParticipant.objects.filter(chat=chat)
            .select_related("user")
            .order_by("joined_at", "id")
        ]
    my_role = membership.role if membership else ""
    can_manage = bool(membership and membership.is_admin())
    is_owner = bool(membership and membership.is_owner())
    invite_url = ""
    if can_manage and chat and chat.invite_token:
        invite_url = request.build_absolute_uri(
            reverse("chat:join_group", kwargs={"token": chat.invite_token})
        )
    return {
        "chat_rows": rows,
        "list_params": params,
        "folders": [
            {"id": folder, "label": label, "href": _page_href(request, chat, params, tab=folder), "current": params["tab"] == folder}
            for folder, label in (
                ("all", "All"),
                ("direct", "Direct"),
                ("group", "Group"),
            )
        ],
        "list_action": _page_href(request, chat, {}),
        "chat": chat,
        "title": chat_title(chat, request.user) if chat else "Chat",
        "peer": peer,
        "peer_profile_url": _profile_url(peer) if peer else "",
        "peer_initials": peer.display_initials() if peer else "",
        "messages_list": messages_list or [],
        "has_older": has_older,
        "form": form,
        "find": find,
        "clear_find_url": _page_href(request, chat, params),
        "back_url": reverse("chat:inbox") + (("?" + chat_querystring(params)) if chat_querystring(params) else ""),
        "my_role": my_role,
        "can_manage": can_manage,
        "is_owner": is_owner,
        "members": members,
        "invite_url": invite_url,
        "group_description": chat.description if chat and chat.is_group else "",
    }


def _page_href(request, chat, params, **overrides):
    """Return the inbox or open-chat URL with list filters applied."""
    if chat is not None:
        base = reverse("chat:room", kwargs={"chat_id": chat.pk})
    else:
        base = reverse("chat:inbox")
    query = chat_querystring(params, **overrides)
    return base + (("?" + query) if query else "")


def _chat_href(chat_id, params):
    """Return a chat URL that keeps the current list filters."""
    query = chat_querystring(params)
    base = reverse("chat:room", kwargs={"chat_id": chat_id})
    return base + (("?" + query) if query else "")


def _profile_url(user):
    """Return the public profile URL for a human account."""
    if user is None:
        return ""
    return reverse("player-profile", kwargs={"username": user.username})


def _inbox_row(chat, viewer):
    """Build one inbox card from an annotated chat.

    Args:
        chat (Chat): Row from :func:`chat.services.visible_chats`.
        viewer: Current user.

    Returns:
        dict: Title, preview, avatar, activity time, and unread badge fields.
    """
    unread = int(chat.unread_count or 0)
    when = ""
    iso = ""
    system = False
    if chat.last_content:
        system = chat.last_kind == Message.KIND_SYSTEM
        prefix = ""
        deleted_last = bool(getattr(chat, "last_deleted_at", None))
        if chat.last_kind == Message.KIND_BOARD:
            if deleted_last:
                body = BOARD_DELETED_PLACEHOLDER
            else:
                prefix = "Board: "
                body = chat.last_content
        else:
            if system:
                prefix = "System: "
            elif chat.last_sender_id and str(chat.last_sender_id) == str(viewer.pk):
                prefix = "You: "
            body = DELETED_PLACEHOLDER if deleted_last else chat.last_content
        preview = prefix + preview_text(body)
        when = format_chat_time(chat.last_sent_at)
        iso = chat.last_sent_at.isoformat() if chat.last_sent_at else ""
    else:
        preview = "No messages yet"
    other = chat.get_other_participant(viewer) if chat.is_direct_message() else None
    title = chat_title(chat, viewer)
    folder = chat_folder(chat)
    group_avatar = chat.avatar_url if chat.is_group and chat.avatar_url else ""
    return {
        "chat": chat,
        "title": title,
        "preview": preview,
        "system": system,
        "when": when,
        "when_iso": iso,
        "unread": unread,
        "unread_label": unread_badge_label(unread),
        "folder": folder,
        "folder_label": _FOLDER_LABELS.get(folder, "Chat"),
        "initials": other.display_initials() if other else _initials(title),
        "avatar_url": other.avatar_url if other and other.has_avatar() else group_avatar,
    }


def _initials(text):
    """Return up to two letters from a chat title."""
    letters = [character for character in (text or "") if character.isalnum()]
    if not letters:
        return "?"
    if len(letters) == 1:
        return letters[0].upper()
    return (letters[0] + letters[1]).upper()


@login_required
def start_direct_chat(request):
    """Show the \"start direct chat\" form or process username submission.

    On success, redirects to the shared :func:`chat_room` for that DM.

    Args:
        request (HttpRequest): GET shows the form; POST expects
            ``other_username``.

    Returns:
        HttpResponse: Form page or redirect to the DM room.
    """
    if request.method == "POST":
        form = StartDirectChatForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["other_username"]
            other = User.objects.filter(
                username__iexact=name,
                is_active=True,
            ).first()
            if other is None:
                form.add_error("other_username", "No user with that username.")
            elif other.pk == request.user.pk:
                form.add_error(
                    "other_username",
                    "You cannot open a direct chat with yourself.",
                )
            else:
                chat, _created = Chat.objects.get_or_create_direct(request.user, other)
                return redirect("chat:room", chat_id=chat.pk)
    else:
        username = (request.GET.get("username") or "").strip()[:150]
        form = StartDirectChatForm(
            initial={"other_username": username} if username else None
        )
    return render(request, "chat/start_direct.html", {"form": form})


@login_required
def start_group_chat(request):
    """Show the new-group form or create a group and open its room."""
    if request.method == "POST":
        form = StartGroupChatForm(request.POST)
        if form.is_valid():
            try:
                chat = create_group(
                    request.user,
                    form.cleaned_data["name"],
                    description=form.cleaned_data.get("description") or "",
                    avatar_url=form.cleaned_data.get("avatar_url") or "",
                )
            except ValueError as exc:
                form.add_error("name", str(exc))
            else:
                return redirect("chat:room", chat_id=chat.pk)
    else:
        form = StartGroupChatForm()
    return render(request, "chat/start_group.html", {"form": form})


@login_required
def join_group_chat(request, token):
    """Show a group invite and join it on POST."""
    chat = Chat.objects.filter(is_group=True, invite_token=token).first()
    if chat is None:
        return render(
            request,
            "chat/join_group.html",
            {"invalid": True, "chat": None, "token": token},
            status=404,
        )
    if chat.has_participant(request.user):
        return redirect("chat:room", chat_id=chat.pk)
    if request.method == "POST":
        try:
            joined = join_by_token(request.user, token)
        except (ValueError, PermissionError) as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "chat/join_group.html",
                {"invalid": False, "chat": chat, "token": token},
            )
        return redirect("chat:room", chat_id=joined.pk)
    return render(
        request,
        "chat/join_group.html",
        {"invalid": False, "chat": chat, "token": token},
    )


@login_required
def chat_room(request, chat_id):
    """Display chronological messages and accept HTTP POST for new lines.

    Live updates use the same Channels consumer as API/WebSocket clients.

    Args:
        request (HttpRequest): GET loads history; POST validates and saves.
        chat_id (uuid.UUID): Primary key of the :class:`~chat.models.Chat`.

    Returns:
        HttpResponse: Room template, redirect after successful send, or redirect
            away if the user is not a participant.
    """
    chat = get_object_or_404(Chat, pk=chat_id)
    if not chat.has_participant(request.user):
        messages.error(request, "You are not a member of this chat.")
        return redirect("chat:inbox")

    params = chat_list_params(request)
    if request.method == "POST":
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            try:
                assert_can_send_message(chat, request.user)
            except PermissionError as exc:
                logger.info(
                    "Chat send denied user=%s chat=%s",
                    request.user.pk,
                    chat.pk,
                )
                messages.error(request, str(exc))
            else:
                message = Message.objects.create(
                    sender=request.user,
                    chat=chat,
                    content=form.cleaned_data["content"],
                )
                broadcast_chat_message(message)
                return redirect(_chat_href(chat.pk, params))
        else:
            logger.info("Chat form rejected user=%s chat=%s", request.user.pk, chat.pk)
    else:
        form = ChatMessageForm()

    find = " ".join((request.GET.get("find") or "").split())[:80]
    msg_list, has_older = message_page(chat, limit=HISTORY_PAGE, text=find)
    membership = get_participant(chat, request.user)
    can_moderate = bool(chat.is_group and membership and membership.is_admin())
    context = _chat_page_context(
        request,
        chat=chat,
        form=form,
        messages_list=[
            _message_row(message, request.user, can_moderate=can_moderate)
            for message in msg_list
        ],
        has_older=has_older,
        find=find,
    )
    return render(request, "chat/home.html", context)


def _message_row(message, viewer, *, can_moderate=False):
    """Describe one history line for the room template.

    Args:
        message: Stored message with ``sender`` loaded.
        viewer: Current user.
        can_moderate (bool): Whether this viewer may delete others' lines.

    Returns:
        dict: Display fields. System lines are never marked as the reader's own.
    """
    system = message.kind == Message.KIND_SYSTEM
    board_kind = message.kind == Message.KIND_BOARD
    deleted = bool(message.deleted_at)
    if deleted and board_kind:
        content = BOARD_DELETED_PLACEHOLDER
    elif deleted:
        content = DELETED_PLACEHOLDER
    else:
        content = message.content
    board_id = str(message.board_id) if message.board_id else ""
    return {
        "id": message.pk,
        "sender_id": message.sender_id,
        "author": "System" if system else message.sender.username,
        "profile_url": "" if system else _profile_url(message.sender),
        "content": content,
        "kind": message.kind,
        "is_mine": (not system and not board_kind) and message.sender_id == viewer.pk,
        "sent_at_iso": message.sent_at.isoformat(),
        "time_label": format_chat_time(message.sent_at),
        "deleted": deleted,
        "edited": bool(message.edited_at) and not deleted,
        "can_edit": can_edit_message(message, viewer),
        "can_delete": can_delete_message(message, viewer),
        "board_id": board_id,
        "board_url": f"/boards/{board_id}/" if board_id else "",
    }
