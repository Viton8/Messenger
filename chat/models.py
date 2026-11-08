"""Chat models for direct and group conversations.

Classes:
    Chat: A direct message thread or a named group.
    ChatParticipant: Membership and role in a chat.
    Message: A stored line inside a chat.
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.utils import timezone

User = get_user_model()


class ChatManager(models.Manager):
    """Custom manager with helpers for direct (1-on-1) chats."""

    def get_or_create_direct(self, user_a, user_b):
        """Return an existing or new direct message chat between two users.

        ``dm_pair_key`` enforces at most one Chat row per unordered user pair.

        Args:
            user_a (User): First participant.
            user_b (User): Second participant.

        Returns:
            tuple[Chat, bool]: The chat instance and True if it was created.

        Raises:
            ValueError: If both arguments refer to the same user.
        """
        if user_a.pk == user_b.pk:
            raise ValueError("Cannot create a direct chat with the same user.")

        key = dm_pair_key(user_a, user_b)
        existing = self.filter(dm_pair_key=key).first()
        if existing:
            return existing, False

        try:
            with transaction.atomic():
                chat = self.create(
                    name="",
                    is_group=False,
                    dm_pair_key=key,
                )
                chat.add_participant(user_a)
                chat.add_participant(user_b)
                return chat, True
        except IntegrityError:
            recovered = self.filter(dm_pair_key=key).first()
            if recovered:
                return recovered, False
            raise


def dm_pair_key(user_a, user_b):
    """Build a stable unique key for an unordered pair of users.

    Args:
        user_a (User): First user.
        user_b (User): Second user.

    Returns:
        str: Two UUIDs in lexicographic order, separated by ``':'``.
    """
    a, b = sorted([str(user_a.pk), str(user_b.pk)])
    return f"{a}:{b}"


class Chat(models.Model):
    """A private 1-on-1 chat or a named group.

    Messages always belong to a Chat. Direct chats use ``dm_pair_key`` so a
    pair of users shares at most one thread.
    """

    objects = ChatManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=60, blank=True)
    description = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True, null=True)
    invite_token = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="Random token for the group invite link. Empty means invites are off.",
    )

    is_group = models.BooleanField(default=False)

    dm_pair_key = models.CharField(
        max_length=73,
        null=True,
        blank=True,
        unique=True,
        help_text="Stable identifier for a 1-on-1 chat (two UUIDs, sorted).",
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Chat"
        verbose_name_plural = "Chats"
        indexes = [
            models.Index(fields=["is_group", "created_at"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        """Return the chat name if available, otherwise fallback to ID."""
        return self.name or f"Chat {self.id}"

    def get_participants(self):
        """Return all users currently participating in this chat.

        Returns:
            QuerySet[User]: Distinct list of users.
        """
        return User.objects.filter(chat_participations__chat=self).distinct()

    def has_participant(self, user):
        """Determine whether a given user is part of this chat.

        Args:
            user (User): The user to check.

        Returns:
            bool: True if the user participates in the chat.
        """
        return ChatParticipant.objects.filter(chat=self, user=user).exists()

    def add_participant(self, user, role="member"):
        """Add a user to the chat or update their role.

        Args:
            user (User): User to add.
            role (str): One of: "owner", "admin", "member".

        Returns:
            tuple(ChatParticipant, bool): participant instance and created flag
        """
        with transaction.atomic():
            participant, created = ChatParticipant.objects.get_or_create(
                chat=self,
                user=user,
                defaults={"role": role},
            )
            if not created and participant.role != role:
                participant.role = role
                participant.save(update_fields=["role"])

        return participant, created

    def remove_participant(self, user):
        """Remove a participant from the chat.

        Args:
            user (User): User to remove.

        Returns:
            int: Number of deleted records (0 or 1).
        """
        return ChatParticipant.objects.filter(chat=self, user=user).delete()[0]

    def get_owners(self):
        """Return all owners of this chat."""
        return ChatParticipant.objects.filter(chat=self, role="owner").select_related("user")

    def get_admins(self):
        """Return all admins (role admin or owner)."""
        return ChatParticipant.objects.filter(
            chat=self, role__in=["admin", "owner"]
        ).select_related("user")

    def is_direct_message(self):
        """Return True if this chat is a private 1-on-1."""
        return not self.is_group

    def get_other_participant(self, user):
        """Return the other user in a direct chat.

        Args:
            user (User): One of the two participants.

        Returns:
            User | None: The counterpart, or None if not applicable.
        """
        if not self.is_direct_message():
            return None
        cached = getattr(self, "_prefetched_objects_cache", {}).get("chatparticipant_set")
        if cached is not None:
            for row in cached:
                if row.user_id != user.pk:
                    return row.user
            return None
        return self.get_participants().exclude(pk=user.pk).first()


class ChatParticipant(models.Model):
    """Represents a user's membership in a chat with assigned permissions.

    Each user can belong to multiple chats and have different roles in each.
    ``last_read_at`` is how far this member has read. It is not shown to
    other people as a read receipt.
    """

    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("member", "Member"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE)
    user = models.ForeignKey(
        "accounts.User", related_name="chat_participations", on_delete=models.CASCADE
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Newest moment this member has caught up to. Empty means nothing is read.",
    )

    class Meta:
        verbose_name = "Chat Participant"
        verbose_name_plural = "Chat Participants"
        unique_together = ("chat", "user")
        indexes = [
            models.Index(fields=["chat", "user"]),
            models.Index(fields=["role"]),
            models.Index(fields=["joined_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} in {self.chat}"

    def is_owner(self):
        """Return True if participant is the owner."""
        return self.role == "owner"

    def is_admin(self):
        """Return True if participant has admin or owner rights."""
        return self.role in ("admin", "owner")

    def promote(self):
        """Promote user to admin."""
        if self.role == "member":
            self.role = "admin"
            self.save(update_fields=["role"])

    def demote(self):
        """Demote admin to member."""
        if self.role == "admin":
            self.role = "member"
            self.save(update_fields=["role"])


class Message(models.Model):
    """A text message inside a chat.

    Messages belong strictly to a ``Chat`` instance. ``kind`` is ``system``
    for a notice the server wrote, or ``board`` for a board card. Members
    cannot choose those kinds themselves.
    """

    KIND_USER = "user"
    KIND_SYSTEM = "system"
    KIND_BOARD = "board"
    KIND_CHOICES = [
        (KIND_USER, "User"),
        (KIND_SYSTEM, "System"),
        (KIND_BOARD, "Board"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="sent_messages"
    )
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    board = models.ForeignKey(
        "boards.Board",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    content = models.TextField()
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_USER)
    sent_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        """Return a concise textual preview."""
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"{self.sender.username}: {preview}"

    def is_private(self):
        """Determine if this is a private 1-on-1 message."""
        return self.chat.is_direct_message()

    def get_chat_context(self):
        """Return structured information about the chat type.

        Returns:
            dict: ``type`` is ``private`` or ``group``; ``name`` is a short label.
        """
        if self.chat.is_group:
            return {"type": "group", "name": self.chat.name or "Group Chat"}
        return {"type": "private", "name": "Private Chat"}

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["sender", "chat", "-sent_at"]),
            models.Index(fields=["-sent_at"]),
        ]
