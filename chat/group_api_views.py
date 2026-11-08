"""REST views for group chats: create, members, invites, leave."""

import logging

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .group_services import (
    add_member,
    create_group,
    get_participant,
    join_by_token,
    leave_group,
    remove_member,
    require_admin,
    require_participant,
    revoke_invite,
    rotate_invite,
    set_member_role,
    update_group,
)
from .models import Chat, ChatParticipant
from .serializers import (
    GroupCreateSerializer,
    GroupJoinSerializer,
    GroupMemberAddSerializer,
    GroupPatchSerializer,
    GroupRoleSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _http_error(exc):
    """Map service errors to DRF responses."""
    if isinstance(exc, PermissionError):
        raise PermissionDenied(str(exc)) from exc
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _invite_url(request, chat, participant):
    """Absolute join URL for admins when an invite token exists."""
    if participant is None or not participant.is_admin() or not chat.invite_token:
        return None
    path = reverse("chat:join_group", kwargs={"token": chat.invite_token})
    return request.build_absolute_uri(path)


def _group_payload(request, chat, participant):
    """Build the retrieve/create body for a group."""
    return {
        "id": str(chat.pk),
        "name": chat.name,
        "description": chat.description,
        "avatar_url": chat.avatar_url or "",
        "is_group": True,
        "my_role": participant.role,
        "member_count": ChatParticipant.objects.filter(chat=chat).count(),
        "invite_url": _invite_url(request, chat, participant),
    }


def _member_payload(row):
    user = row.user
    return {
        "id": str(user.pk),
        "username": user.username,
        "role": row.role,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
        "initials": user.display_initials(),
        "avatar_url": user.avatar_url or "",
    }


class GroupCreateAPIView(APIView):
    """Create a group. The caller becomes owner."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Create a named group and return its detail."""
        ser = GroupCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            chat = create_group(
                request.user,
                ser.validated_data["name"],
                description=ser.validated_data.get("description") or "",
                avatar_url=ser.validated_data.get("avatar_url") or "",
            )
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        participant = get_participant(chat, request.user)
        return Response(
            _group_payload(request, chat, participant),
            status=status.HTTP_201_CREATED,
        )


class GroupJoinAPIView(APIView):
    """Join a group with an invite token."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Add the caller when the token is currently valid."""
        ser = GroupJoinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            chat = join_by_token(request.user, ser.validated_data["token"])
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        participant = get_participant(chat, request.user)
        return Response(_group_payload(request, chat, participant))


class GroupDetailAPIView(APIView):
    """Retrieve or update one group."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, chat_id):
        """Return group metadata for a member."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            participant = require_participant(chat, request.user)
        except PermissionError as exc:
            return _http_error(exc)
        return Response(_group_payload(request, chat, participant))

    def patch(self, request, chat_id):
        """Change name and/or description. Admin or owner."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        ser = GroupPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            chat = update_group(
                chat,
                request.user,
                name=ser.validated_data.get("name"),
                description=ser.validated_data.get("description"),
            )
            participant = require_participant(chat, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_group_payload(request, chat, participant))


class GroupMembersAPIView(APIView):
    """List members or add one by username."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, chat_id):
        """Return membership rows for a participant."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            require_participant(chat, request.user)
        except PermissionError as exc:
            return _http_error(exc)
        rows = (
            ChatParticipant.objects.filter(chat=chat)
            .select_related("user")
            .order_by("joined_at", "id")
        )
        return Response([_member_payload(row) for row in rows])

    def post(self, request, chat_id):
        """Add an active user by username. Admin or owner."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        ser = GroupMemberAddSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            row = add_member(chat, request.user, ser.validated_data["username"])
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_member_payload(row), status=status.HTTP_201_CREATED)


class GroupMemberDetailAPIView(APIView):
    """Remove one member."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, chat_id, user_id):
        """Remove a member following role rules."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        target = get_object_or_404(User, pk=user_id)
        try:
            remove_member(chat, request.user, target)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupMemberRoleAPIView(APIView):
    """Promote or demote a member. Owner only."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, chat_id, user_id):
        """Set ``role`` to admin or member."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        target = get_object_or_404(User, pk=user_id)
        ser = GroupRoleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            row = set_member_role(chat, request.user, target, ser.validated_data["role"])
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_member_payload(row))


class GroupLeaveAPIView(APIView):
    """Leave a group. Last member deletes it."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, chat_id):
        """Remove the caller. 204 when the group is gone."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            leave_group(chat, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupInviteAPIView(APIView):
    """Create, rotate, or revoke the invite token."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, chat_id):
        """Issue a new invite token, replacing any previous one."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            rotate_invite(chat, request.user)
            participant = require_admin(chat, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_group_payload(request, chat, participant))

    def delete(self, request, chat_id):
        """Clear the invite token."""
        chat = get_object_or_404(Chat, pk=chat_id, is_group=True)
        try:
            revoke_invite(chat, request.user)
            participant = require_admin(chat, request.user)
        except (ValueError, PermissionError) as exc:
            return _http_error(exc)
        return Response(_group_payload(request, chat, participant))
