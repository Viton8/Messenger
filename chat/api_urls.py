"""URL routes for the chat REST API.

These patterns are included under ``api/chat/`` in the project root ``urls.py``, so
effective paths are:

    /api/chat/chats/
    /api/chat/chats/direct/
    /api/chat/groups/
    /api/chat/users/?q=
    /api/chat/chats/<uuid>/messages/
    /api/chat/chats/<uuid>/read/
    /api/chat/groups/<uuid>/boards/
"""

from django.urls import path

from .api_views import (
    ChatListAPIView,
    ChatMessageDetailAPIView,
    ChatMessagesAPIView,
    ChatReadAPIView,
    DirectChatCreateAPIView,
    UserSearchAPIView,
)
from boards.api_views import GroupBoardDetailAPIView, GroupBoardListAPIView
from .group_api_views import (
    GroupCreateAPIView,
    GroupDetailAPIView,
    GroupInviteAPIView,
    GroupJoinAPIView,
    GroupLeaveAPIView,
    GroupMemberDetailAPIView,
    GroupMemberRoleAPIView,
    GroupMembersAPIView,
)

urlpatterns = [
    path("chats/", ChatListAPIView.as_view(), name="chat-list"),
    path("chats/direct/", DirectChatCreateAPIView.as_view(), name="chat-direct-create"),
    path("groups/", GroupCreateAPIView.as_view(), name="chat-group-create"),
    path("groups/join/", GroupJoinAPIView.as_view(), name="chat-group-join"),
    path("groups/<uuid:chat_id>/", GroupDetailAPIView.as_view(), name="chat-group-detail"),
    path(
        "groups/<uuid:chat_id>/members/",
        GroupMembersAPIView.as_view(),
        name="chat-group-members",
    ),
    path(
        "groups/<uuid:chat_id>/members/<uuid:user_id>/",
        GroupMemberDetailAPIView.as_view(),
        name="chat-group-member-detail",
    ),
    path(
        "groups/<uuid:chat_id>/members/<uuid:user_id>/role/",
        GroupMemberRoleAPIView.as_view(),
        name="chat-group-member-role",
    ),
    path(
        "groups/<uuid:chat_id>/leave/",
        GroupLeaveAPIView.as_view(),
        name="chat-group-leave",
    ),
    path(
        "groups/<uuid:chat_id>/invite/",
        GroupInviteAPIView.as_view(),
        name="chat-group-invite",
    ),
    path(
        "groups/<uuid:chat_id>/boards/",
        GroupBoardListAPIView.as_view(),
        name="chat-group-boards",
    ),
    path(
        "groups/<uuid:chat_id>/boards/<uuid:board_id>/",
        GroupBoardDetailAPIView.as_view(),
        name="chat-group-board-detail",
    ),
    path("users/", UserSearchAPIView.as_view(), name="chat-user-search"),
    path(
        "chats/<uuid:chat_id>/messages/",
        ChatMessagesAPIView.as_view(),
        name="chat-messages",
    ),
    path(
        "chats/<uuid:chat_id>/messages/<uuid:message_id>/",
        ChatMessageDetailAPIView.as_view(),
        name="chat-message-detail",
    ),
    path(
        "chats/<uuid:chat_id>/read/",
        ChatReadAPIView.as_view(),
        name="chat-read",
    ),
]
