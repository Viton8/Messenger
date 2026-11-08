"""Tests for group REST endpoints, membership rules, and message edit/delete."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test.utils import override_settings
from django.urls import reverse
from rest_framework import status

from accounts.models import Block
from chat.group_services import create_group, rotate_invite, set_member_role
from chat.models import Chat, ChatParticipant, Message
from chat.services import DELETED_PLACEHOLDER, message_public


@pytest.mark.django_db
class TestGroupAPI:
    """REST rules for create, members, roles, invites, and leave."""

    def _login(self, api_client, user):
        api_client.force_login(user)

    def _create(self, api_client, user, name="Team", **extra):
        self._login(api_client, user)
        response = api_client.post(
            reverse("chat-group-create"),
            {"name": name, **extra},
            format="json",
        )
        return response

    def test_create_group_makes_owner(self, api_client, test_user):
        """POST /groups/ stores a named group and the caller is owner."""
        response = self._create(api_client, test_user, name="  Ops desk  ")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Ops desk"
        assert response.data["my_role"] == "owner"
        assert response.data["is_group"] is True
        assert response.data["member_count"] == 1
        chat = Chat.objects.get(pk=response.data["id"])
        assert chat.is_group is True
        row = ChatParticipant.objects.get(chat=chat, user=test_user)
        assert row.role == "owner"
        assert Message.objects.filter(
            chat=chat, kind=Message.KIND_SYSTEM, content="player1 created the group."
        ).exists()

    def test_create_rejects_empty_name(self, api_client, test_user):
        """A blank group name is 400."""
        response = self._create(api_client, test_user, name="   ")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Chat.objects.filter(is_group=True).count() == 0

    def test_non_member_cannot_get_group(self, api_client, test_user, second_user):
        """A signed-in outsider gets 403, not the group body."""
        created = self._create(api_client, test_user)
        chat_id = created.data["id"]
        self._login(api_client, second_user)
        response = api_client.get(reverse("chat-group-detail", kwargs={"chat_id": chat_id}))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_group_is_404(self, api_client, test_user):
        """Unknown group id is 404."""
        self._login(api_client, test_user)
        response = api_client.get(
            reverse(
                "chat-group-detail",
                kwargs={"chat_id": "00000000-0000-0000-0000-000000000001"},
            )
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_member_cannot_patch_or_add_or_invite(
        self, api_client, test_user, second_user, user_factory
    ):
        """A plain member cannot change settings, add people, or issue invites."""
        extra = user_factory(username="helper")
        created = self._create(api_client, test_user)
        chat_id = created.data["id"]
        add = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": second_user.username},
            format="json",
        )
        assert add.status_code == status.HTTP_201_CREATED
        self._login(api_client, second_user)
        patch = api_client.patch(
            reverse("chat-group-detail", kwargs={"chat_id": chat_id}),
            {"name": "Hijacked"},
            format="json",
        )
        assert patch.status_code == status.HTTP_403_FORBIDDEN
        add_denied = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": extra.username},
            format="json",
        )
        assert add_denied.status_code == status.HTTP_403_FORBIDDEN
        invite = api_client.post(reverse("chat-group-invite", kwargs={"chat_id": chat_id}))
        assert invite.status_code == status.HTTP_403_FORBIDDEN
        chat = Chat.objects.get(pk=chat_id)
        assert chat.name == "Team"
        assert ChatParticipant.objects.filter(chat=chat, user=extra).exists() is False

    def test_admin_cannot_remove_admin_or_owner(
        self, api_client, test_user, second_user, user_factory
    ):
        """An admin may remove a member, not another admin or the owner."""
        lead = second_user
        helper = user_factory(username="helper")
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": lead.username},
            format="json",
        )
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": helper.username},
            format="json",
        )
        set_member_role(chat, test_user, lead, "admin")
        self._login(api_client, lead)
        against_owner = api_client.delete(
            reverse(
                "chat-group-member-detail",
                kwargs={"chat_id": chat.pk, "user_id": test_user.pk},
            )
        )
        assert against_owner.status_code == status.HTTP_403_FORBIDDEN
        against_self_admin = api_client.delete(
            reverse(
                "chat-group-member-detail",
                kwargs={"chat_id": chat.pk, "user_id": lead.pk},
            )
        )
        assert against_self_admin.status_code == status.HTTP_403_FORBIDDEN
        against_member = api_client.delete(
            reverse(
                "chat-group-member-detail",
                kwargs={"chat_id": chat.pk, "user_id": helper.pk},
            )
        )
        assert against_member.status_code == status.HTTP_204_NO_CONTENT
        assert ChatParticipant.objects.filter(chat=chat, user=helper).exists() is False

    def test_owner_leave_promotes_earliest_admin(
        self, api_client, test_user, second_user, user_factory
    ):
        """Owner leave transfers to the earliest admin, not a later member."""
        lead = second_user
        helper = user_factory(username="helper")
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": lead.username},
            format="json",
        )
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": helper.username},
            format="json",
        )
        set_member_role(chat, test_user, lead, "admin")
        leave = api_client.post(reverse("chat-group-leave", kwargs={"chat_id": chat.pk}))
        assert leave.status_code == status.HTTP_204_NO_CONTENT
        chat.refresh_from_db()
        assert ChatParticipant.objects.filter(chat=chat, user=test_user).exists() is False
        assert ChatParticipant.objects.get(chat=chat, user=lead).role == "owner"
        assert ChatParticipant.objects.get(chat=chat, user=helper).role == "member"
        assert Message.objects.filter(
            chat=chat, kind=Message.KIND_SYSTEM, content="player1 left the group."
        ).exists()

    def test_last_member_leave_deletes_chat(self, api_client, test_user):
        """When the last person leaves, the group row is gone."""
        created = self._create(api_client, test_user)
        chat_id = created.data["id"]
        leave = api_client.post(reverse("chat-group-leave", kwargs={"chat_id": chat_id}))
        assert leave.status_code == status.HTTP_204_NO_CONTENT
        assert Chat.objects.filter(pk=chat_id).exists() is False

    @override_settings(GROUP_MAX_MEMBERS=2)
    def test_member_cap_rejects_the_next_join(
        self, api_client, test_user, second_user, user_factory
    ):
        """Add and join refuse a group that already has GROUP_MAX_MEMBERS people."""
        extra = user_factory(username="helper")
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        ok = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": second_user.username},
            format="json",
        )
        assert ok.status_code == status.HTTP_201_CREATED
        full = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": extra.username},
            format="json",
        )
        assert full.status_code == status.HTTP_400_BAD_REQUEST
        assert "full" in str(full.data["detail"]).lower()
        rotate_invite(chat, test_user)
        self._login(api_client, extra)
        joined = api_client.post(
            reverse("chat-group-join"),
            {"token": chat.invite_token},
            format="json",
        )
        assert joined.status_code == status.HTTP_400_BAD_REQUEST
        assert ChatParticipant.objects.filter(chat=chat).count() == 2

    def test_add_blocked_when_target_blocked_actor(
        self, api_client, test_user, second_user
    ):
        """Add is 403 when the target has blocked the admin."""
        created = self._create(api_client, test_user)
        chat_id = created.data["id"]
        Block.objects.create(blocker=second_user, blocked=test_user)
        response = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": second_user.username},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert ChatParticipant.objects.filter(
            chat_id=chat_id, user=second_user
        ).exists() is False

    def test_join_by_token_ignores_pairwise_block(
        self, api_client, test_user, second_user
    ):
        """A blocked user may still join through a valid invite token."""
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        rotate_invite(chat, test_user)
        Block.objects.create(blocker=second_user, blocked=test_user)
        self._login(api_client, second_user)
        response = api_client.post(
            reverse("chat-group-join"),
            {"token": chat.invite_token},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert ChatParticipant.objects.filter(chat=chat, user=second_user).exists()
        assert Message.objects.filter(
            chat=chat, kind=Message.KIND_SYSTEM, content="player2 joined the group."
        ).exists()

    def test_revoked_token_cannot_join(self, api_client, test_user, second_user):
        """DELETE invite then join with the old token fails."""
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        rotate_invite(chat, test_user)
        token = chat.invite_token
        revoke = api_client.delete(reverse("chat-group-invite", kwargs={"chat_id": chat.pk}))
        assert revoke.status_code == status.HTTP_200_OK
        assert revoke.data["invite_url"] is None
        self._login(api_client, second_user)
        response = api_client.post(
            reverse("chat-group-join"),
            {"token": token},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_get_hides_invite_url(self, api_client, test_user, second_user):
        """Only admin and owner receive invite_url."""
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        rotate_invite(chat, test_user)
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": second_user.username},
            format="json",
        )
        owner_get = api_client.get(reverse("chat-group-detail", kwargs={"chat_id": chat.pk}))
        assert owner_get.data["invite_url"]
        self._login(api_client, second_user)
        member_get = api_client.get(reverse("chat-group-detail", kwargs={"chat_id": chat.pk}))
        assert member_get.status_code == status.HTTP_200_OK
        assert member_get.data["invite_url"] is None

    def test_owner_changes_roles(self, api_client, test_user, second_user):
        """Owner may promote and demote; the owner row cannot be changed."""
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": second_user.username},
            format="json",
        )
        promote = api_client.post(
            reverse(
                "chat-group-member-role",
                kwargs={"chat_id": chat.pk, "user_id": second_user.pk},
            ),
            {"role": "admin"},
            format="json",
        )
        assert promote.status_code == status.HTTP_200_OK
        assert promote.data["role"] == "admin"
        demote = api_client.post(
            reverse(
                "chat-group-member-role",
                kwargs={"chat_id": chat.pk, "user_id": second_user.pk},
            ),
            {"role": "member"},
            format="json",
        )
        assert demote.data["role"] == "member"
        own = api_client.post(
            reverse(
                "chat-group-member-role",
                kwargs={"chat_id": chat.pk, "user_id": test_user.pk},
            ),
            {"role": "member"},
            format="json",
        )
        assert own.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cannot_change_roles(self, api_client, test_user, second_user, user_factory):
        """Role changes are owner-only."""
        helper = user_factory(username="helper")
        created = self._create(api_client, test_user)
        chat = Chat.objects.get(pk=created.data["id"])
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": second_user.username},
            format="json",
        )
        api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat.pk}),
            {"username": helper.username},
            format="json",
        )
        set_member_role(chat, test_user, second_user, "admin")
        self._login(api_client, second_user)
        response = api_client.post(
            reverse(
                "chat-group-member-role",
                kwargs={"chat_id": chat.pk, "user_id": helper.pk},
            ),
            {"role": "admin"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @override_settings(GROUP_MEMBER_RATE_LIMIT=1)
    def test_add_rate_limit_counts_only_success(self, api_client, test_user, user_factory):
        """A refused add does not consume the window; a success does."""
        cache.clear()
        first = user_factory(username="helper")
        second = user_factory(username="joiner")
        created = self._create(api_client, test_user)
        chat_id = created.data["id"]
        denied = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": "missing-user"},
            format="json",
        )
        assert denied.status_code == status.HTTP_400_BAD_REQUEST
        ok = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": first.username},
            format="json",
        )
        assert ok.status_code == status.HTTP_201_CREATED
        limited = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": chat_id}),
            {"username": second.username},
            format="json",
        )
        assert limited.status_code == status.HTTP_400_BAD_REQUEST
        assert limited.data["detail"] == "Too many attempts. Try again later."
        assert ChatParticipant.objects.filter(chat_id=chat_id, user=second).exists() is False

    def test_inactive_user_is_not_added(self, api_client, test_user, user_factory):
        """Inactive accounts cannot be added."""
        quiet = user_factory(username="quietone", is_active=False)
        created = self._create(api_client, test_user)
        response = api_client.post(
            reverse("chat-group-members", kwargs={"chat_id": created.data["id"]}),
            {"username": quiet.username},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestMessageEditDeleteAPI:
    """PATCH/DELETE own messages; group admins may delete others' user lines."""

    def _login(self, api_client, user):
        api_client.force_login(user)

    def _url(self, chat, message):
        return reverse(
            "chat-message-detail",
            kwargs={"chat_id": chat.pk, "message_id": message.pk},
        )

    def test_owner_edits_own_message(self, api_client, test_user, second_user):
        """PATCH updates content, sets edited_at, and fans out message_updated."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(sender=test_user, chat=chat, content="old")
        self._login(api_client, test_user)
        with patch("chat.api_views.broadcast_message_updated") as fanout:
            response = api_client.patch(
                self._url(chat, message),
                {"content": "  new text  "},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["content"] == "new text"
        assert response.data["edited_at"]
        assert response.data["deleted"] is False
        fanout.assert_called_once()
        message.refresh_from_db()
        assert message.content == "new text"
        assert message.edited_at is not None

    def test_cannot_edit_someone_elses_message(
        self, api_client, test_user, second_user
    ):
        """Editing another person's line is 403."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(sender=second_user, chat=chat, content="theirs")
        self._login(api_client, test_user)
        response = api_client.patch(
            self._url(chat, message),
            {"content": "stolen"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        message.refresh_from_db()
        assert message.content == "theirs"

    def test_admin_can_delete_others_in_group_member_cannot(
        self, api_client, test_user, second_user, user_factory
    ):
        """Group admin/owner may soft-delete another user line; a member may not."""
        helper = user_factory(username="helper")
        chat = create_group(test_user, "Desk")
        chat.add_participant(second_user, role="member")
        chat.add_participant(helper, role="member")
        message = Message.objects.create(sender=helper, chat=chat, content="keep-secret")
        self._login(api_client, second_user)
        member_try = api_client.delete(self._url(chat, message))
        assert member_try.status_code == status.HTTP_403_FORBIDDEN
        self._login(api_client, test_user)
        with patch("chat.api_views.broadcast_message_deleted") as fanout:
            deleted = api_client.delete(self._url(chat, message))
        assert deleted.status_code == status.HTTP_200_OK
        assert deleted.data["deleted"] is True
        assert deleted.data["content"] == DELETED_PLACEHOLDER
        fanout.assert_called_once()
        message.refresh_from_db()
        assert message.deleted_at is not None
        assert message.content == "keep-secret"

    def test_member_cannot_delete_others_in_direct(
        self, api_client, test_user, second_user
    ):
        """In a DM, only the sender may delete the line."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(sender=second_user, chat=chat, content="private")
        self._login(api_client, test_user)
        response = api_client.delete(self._url(chat, message))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        message.refresh_from_db()
        assert message.deleted_at is None

    def test_system_message_cannot_be_edited_or_deleted(
        self, api_client, test_user
    ):
        """System notices are not user-editable."""
        chat = create_group(test_user, "Desk")
        notice = Message.objects.filter(chat=chat, kind=Message.KIND_SYSTEM).get()
        self._login(api_client, test_user)
        patch = api_client.patch(
            self._url(chat, notice),
            {"content": "rewritten"},
            format="json",
        )
        delete = api_client.delete(self._url(chat, notice))
        assert patch.status_code == status.HTTP_403_FORBIDDEN
        assert delete.status_code == status.HTTP_403_FORBIDDEN
        notice.refresh_from_db()
        assert notice.deleted_at is None

    def test_deleted_message_is_not_searchable(
        self, api_client, test_user, second_user
    ):
        """Search skips the stored text of a soft-deleted line."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(
            sender=test_user, chat=chat, content="hidden-needle"
        )
        self._login(api_client, test_user)
        api_client.delete(self._url(chat, message))
        listed = api_client.get(
            reverse("chat-messages", kwargs={"chat_id": chat.pk}),
            {"q": "needle", "envelope": "1"},
        )
        assert listed.status_code == status.HTTP_200_OK
        assert listed.data["results"] == []
        all_rows = api_client.get(reverse("chat-messages", kwargs={"chat_id": chat.pk}))
        found = next(row for row in all_rows.data if row["id"] == str(message.pk))
        assert found["content"] == DELETED_PLACEHOLDER
        assert found["deleted"] is True

    def test_message_public_payload_includes_edit_flags(self, test_user, second_user):
        """WebSocket JSON exposes edited_at and deleted without the original body."""
        chat, _ = Chat.objects.get_or_create_direct(test_user, second_user)
        message = Message.objects.create(sender=test_user, chat=chat, content="secret")
        payload = message_public(message)
        assert payload["deleted"] is False
        assert payload["edited_at"] is None
        message.deleted_at = message.sent_at
        message.save(update_fields=["deleted_at"])
        gone = message_public(message)
        assert gone["deleted"] is True
        assert gone["content"] == DELETED_PLACEHOLDER
