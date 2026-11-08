"""Server-side group membership, invites, and role changes.

The browser is not trusted. Every add, remove, leave, role change, and invite
action is checked here before the database is updated.
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Block

from .models import Chat, ChatParticipant, Message
from .services import broadcast_chat_message

logger = logging.getLogger(__name__)

User = get_user_model()

GROUP_NAME_MAX = 60
GROUP_DESCRIPTION_MAX = 500
TOO_MANY_GROUP_ACTIONS = "Too many attempts. Try again later."
GROUP_FULL = "This group is full."


def normalize_group_name(name):
    """Strip and require a group name of 1–60 characters.

    Args:
        name: Submitted name.

    Returns:
        str: Cleaned name.

    Raises:
        ValueError: When the name is empty or too long.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Group name is required.")
    if len(cleaned) > GROUP_NAME_MAX:
        raise ValueError("Use %d characters or fewer." % GROUP_NAME_MAX)
    return cleaned


def normalize_group_description(description):
    """Strip a description and cap it at 500 characters.

    Args:
        description: Submitted description, or None.

    Returns:
        str: Cleaned description, possibly empty.

    Raises:
        ValueError: When the text is longer than 500 characters.
    """
    cleaned = (description or "").strip()
    if len(cleaned) > GROUP_DESCRIPTION_MAX:
        raise ValueError("Use %d characters or fewer." % GROUP_DESCRIPTION_MAX)
    return cleaned


def normalize_avatar_url(avatar_url):
    """Return a stripped URL or empty string.

    Args:
        avatar_url: Submitted URL, or None.

    Returns:
        str: Cleaned URL, or empty when none was given.
    """
    return (avatar_url or "").strip()


def require_group(chat):
    """Raise if ``chat`` is not a group.

    Args:
        chat: Chat instance.

    Raises:
        ValueError: When the chat is a direct message.
    """
    if not chat.is_group:
        raise ValueError("This chat is not a group.")


def get_participant(chat, user):
    """Return the membership row, or None."""
    if user is None or not getattr(user, "pk", None):
        return None
    return ChatParticipant.objects.filter(chat=chat, user=user).select_related("user").first()


def require_participant(chat, user):
    """Return the membership row or raise.

    Raises:
        PermissionError: When the user is not a member.
    """
    participant = get_participant(chat, user)
    if participant is None:
        raise PermissionError("You are not a member of this chat.")
    return participant


def require_admin(chat, user):
    """Return the membership row when the user is admin or owner.

    Raises:
        PermissionError: When the user is missing or only a member.
    """
    participant = require_participant(chat, user)
    if not participant.is_admin():
        raise PermissionError("You cannot manage this group.")
    return participant


def require_owner(chat, user):
    """Return the membership row when the user is the owner.

    Raises:
        PermissionError: When the user is not the owner.
    """
    participant = require_participant(chat, user)
    if not participant.is_owner():
        raise PermissionError("Only the owner can change roles.")
    return participant


def record_system(chat, actor, text):
    """Store a system notice and publish it on the chat channel.

    Args:
        chat: Group chat.
        actor: User who caused the event; stored as ``sender``.
        text (str): English notice body.

    Returns:
        Message: The stored system line.
    """
    message = Message.objects.create(
        sender=actor,
        chat=chat,
        content=text,
        kind=Message.KIND_SYSTEM,
    )
    broadcast_chat_message(message)
    return message


def _new_invite_token():
    """Return a unique invite token."""
    return secrets.token_urlsafe(32)


def _member_count(chat):
    return ChatParticipant.objects.filter(chat=chat).count()


def _group_full(chat):
    return _member_count(chat) >= int(settings.GROUP_MAX_MEMBERS)


def _rate_key(user, kind):
    return f"chat-group:{kind}:{user.pk}"


def group_member_action_blocked(user, kind):
    """Return True when this user is over the add/join limit.

    Cache failures fail open, matching the account email limiter.

    Args:
        user: Acting user.
        kind (str): ``add`` or ``join``.

    Returns:
        bool: True when the action must be refused.
    """
    limit = int(settings.GROUP_MEMBER_RATE_LIMIT)
    window = int(settings.GROUP_MEMBER_RATE_WINDOW)
    key = _rate_key(user, kind)
    try:
        count = cache.get(key, 0) or 0
    except Exception:
        logger.warning("Group member rate limit cache is unavailable")
        return False
    if count >= limit:
        logger.info("Group %s blocked for user=%s", kind, user.pk)
        return True
    return False


def _record_group_member_action(user, kind):
    """Count a successful add or join against the user's window."""
    window = int(settings.GROUP_MEMBER_RATE_WINDOW)
    key = _rate_key(user, kind)
    try:
        if cache.add(key, 1, timeout=window):
            return
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
    except Exception:
        logger.warning("Group member rate limit cache is unavailable")


def create_group(user, name, description="", avatar_url=""):
    """Create a group and make ``user`` the owner.

    Args:
        user: Authenticated creator.
        name: Group title.
        description: Optional description.
        avatar_url: Optional image URL.

    Returns:
        Chat: The new group.
    """
    name = normalize_group_name(name)
    description = normalize_group_description(description)
    avatar_url = normalize_avatar_url(avatar_url) or None
    with transaction.atomic():
        chat = Chat.objects.create(
            name=name,
            description=description,
            avatar_url=avatar_url,
            is_group=True,
        )
        chat.add_participant(user, role="owner")
    record_system(chat, user, f"{user.username} created the group.")
    return chat


def update_group(chat, user, *, name=None, description=None):
    """Change name and/or description. Admin or owner only.

    Args:
        chat: Group chat.
        user: Acting member.
        name: New name, or None to leave it.
        description: New description, or None to leave it.

    Returns:
        Chat: The updated group.
    """
    require_group(chat)
    require_admin(chat, user)
    fields = []
    if name is not None:
        chat.name = normalize_group_name(name)
        fields.append("name")
    if description is not None:
        chat.description = normalize_group_description(description)
        fields.append("description")
    if fields:
        chat.save(update_fields=fields)
    return chat


def add_member(chat, actor, username):
    """Add an active user by username. Admin or owner only.

    Does not count against the rate limit when the call is refused for
    rights, a full group, a missing account, or a block.

    Args:
        chat: Group chat.
        actor: Admin or owner adding the member.
        username: Target username.

    Returns:
        ChatParticipant: The new membership.

    Raises:
        PermissionError: When the actor lacks rights or is blocked by the target.
        ValueError: When the target cannot be added.
    """
    require_group(chat)
    require_admin(chat, actor)
    name = (username or "").strip()
    if not name:
        raise ValueError("Username is required.")
    target = User.objects.filter(username__iexact=name, is_active=True).first()
    if target is None:
        raise ValueError("No user with that username.")
    if ChatParticipant.objects.filter(chat=chat, user=target).exists():
        raise ValueError("That user is already in this group.")
    if Block.objects.filter(blocker=target, blocked=actor).exists():
        raise PermissionError("You cannot add that user.")
    if _group_full(chat):
        raise ValueError(GROUP_FULL)
    if group_member_action_blocked(actor, "add"):
        raise ValueError(TOO_MANY_GROUP_ACTIONS)
    participant, created = chat.add_participant(target, role="member")
    if created:
        _record_group_member_action(actor, "add")
        record_system(chat, actor, f"{target.username} was added to the group.")
    return participant


def remove_member(chat, actor, target_user):
    """Remove a member. Admin cannot remove admin or owner. Owner cannot be removed.

    Args:
        chat: Group chat.
        actor: Admin or owner.
        target_user: Member to remove.

    Returns:
        Chat: The group, still existing.
    """
    require_group(chat)
    actor_row = require_admin(chat, actor)
    target_row = ChatParticipant.objects.filter(chat=chat, user=target_user).first()
    if target_row is None:
        raise ValueError("That user is not in this group.")
    if target_row.is_owner():
        raise PermissionError("The owner cannot be removed.")
    if target_row.role == "admin" and not actor_row.is_owner():
        raise PermissionError("You cannot remove another admin.")
    target_row.delete()
    from boards.broadcast import force_close_user_boards

    force_close_user_boards(target_user.pk, chat.pk)
    record_system(chat, actor, f"{target_user.username} was removed from the group.")
    return chat


def leave_group(chat, user):
    """Remove ``user`` from the group and transfer ownership if needed.

    Returns:
        tuple[Chat | None, bool]: The group (or None if it was deleted) and
        whether the chat row was deleted.
    """
    require_group(chat)
    participant = require_participant(chat, user)
    was_owner = participant.is_owner()
    from boards.broadcast import force_close_board, force_close_user_boards
    from boards.models import Board

    board_ids = list(Board.objects.filter(chat=chat).values_list("pk", flat=True))
    with transaction.atomic():
        others = ChatParticipant.objects.select_for_update().filter(chat=chat).exclude(
            user=user
        )
        if not others.exists():
            for board_id in board_ids:
                force_close_board(board_id)
            force_close_user_boards(user.pk, chat.pk)
            chat.delete()
            return None, True
        successor = None
        if was_owner:
            successor = (
                others.filter(role="admin").order_by("joined_at", "id").first()
                or others.order_by("joined_at", "id").first()
            )
            if successor is not None:
                successor.role = "owner"
                successor.save(update_fields=["role"])
        participant.delete()
    force_close_user_boards(user.pk, chat.pk)
    record_system(chat, user, f"{user.username} left the group.")
    return chat, False


def set_member_role(chat, actor, target_user, role):
    """Promote or demote between member and admin. Owner only.

    Args:
        chat: Group chat.
        actor: Current owner.
        target_user: Member whose role changes.
        role (str): ``admin`` or ``member``.

    Returns:
        ChatParticipant: Updated row.
    """
    require_group(chat)
    require_owner(chat, actor)
    if role not in ("admin", "member"):
        raise ValueError("Role must be admin or member.")
    target_row = ChatParticipant.objects.filter(chat=chat, user=target_user).first()
    if target_row is None:
        raise ValueError("That user is not in this group.")
    if target_row.is_owner():
        raise PermissionError("The owner's role cannot be changed.")
    if target_row.user_id == actor.pk:
        raise PermissionError("The owner's role cannot be changed.")
    previous = target_row.role
    if previous == role:
        return target_row
    target_row.role = role
    target_row.save(update_fields=["role"])
    if role == "admin":
        record_system(chat, actor, f"{target_user.username} is now an admin.")
    else:
        record_system(chat, actor, f"{target_user.username} is now a member.")
    return target_row


def rotate_invite(chat, actor):
    """Create or replace the invite token. Admin or owner only.

    Returns:
        str: The new token.
    """
    require_group(chat)
    require_admin(chat, actor)
    for _ in range(5):
        token = _new_invite_token()
        chat.invite_token = token
        try:
            chat.save(update_fields=["invite_token"])
            return token
        except IntegrityError:
            continue
    raise ValueError("Could not create an invite link.")


def revoke_invite(chat, actor):
    """Clear the invite token. Admin or owner only."""
    require_group(chat)
    require_admin(chat, actor)
    chat.invite_token = None
    chat.save(update_fields=["invite_token"])
    return chat


def join_by_token(user, token):
    """Add ``user`` to the group that currently uses ``token``.

    Pairwise blocks are not applied. A full group and the rate limit are.

    Args:
        user: Signed-in joiner.
        token: Invite token.

    Returns:
        Chat: The group joined.

    Raises:
        ValueError: Invalid token, already a member, full, or rate limited.
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("Invite link is not valid.")
    chat = Chat.objects.filter(is_group=True, invite_token=token).first()
    if chat is None:
        raise ValueError("Invite link is not valid.")
    if ChatParticipant.objects.filter(chat=chat, user=user).exists():
        return chat
    if not user.is_active:
        raise ValueError("Invite link is not valid.")
    if _group_full(chat):
        raise ValueError(GROUP_FULL)
    if group_member_action_blocked(user, "join"):
        raise ValueError(TOO_MANY_GROUP_ACTIONS)
    chat.add_participant(user, role="member")
    _record_group_member_action(user, "join")
    record_system(chat, user, f"{user.username} joined the group.")
    return chat


def can_edit_message(message, user):
    """Return True if ``user`` may change the text of ``message``."""
    if message.kind != Message.KIND_USER or message.deleted_at:
        return False
    return message.sender_id == user.pk


def can_delete_message(message, user):
    """Return True if ``user`` may soft-delete ``message``."""
    if message.kind != Message.KIND_USER or message.deleted_at:
        return False
    if message.sender_id == user.pk:
        return True
    if not message.chat.is_group:
        return False
    participant = get_participant(message.chat, user)
    return bool(participant and participant.is_admin())


def edit_message(message, user, content):
    """Change the text of an own user message.

    Args:
        message: Stored line.
        user: Editor.
        content: New body.

    Returns:
        Message: Updated row.

    Raises:
        PermissionError: When the user may not edit.
        ValueError: When the body is empty or too long.
    """
    if not message.chat.has_participant(user):
        raise PermissionError("You are not a member of this chat.")
    if not can_edit_message(message, user):
        raise PermissionError("You cannot edit this message.")
    text = (content or "").strip()
    if not text:
        raise ValueError("Message cannot be empty.")
    if len(text) > 10000:
        raise ValueError("Message exceeds maximum length.")
    message.content = text
    message.edited_at = timezone.now()
    message.save(update_fields=["content", "edited_at"])
    return message


def soft_delete_message(message, user):
    """Mark a user message deleted without removing the row.

    Args:
        message: Stored line.
        user: Actor.

    Returns:
        Message: Updated row.

    Raises:
        PermissionError: When the user may not delete.
    """
    if not message.chat.has_participant(user):
        raise PermissionError("You are not a member of this chat.")
    if not can_delete_message(message, user):
        raise PermissionError("You cannot delete this message.")
    message.deleted_at = timezone.now()
    message.save(update_fields=["deleted_at"])
    return message
