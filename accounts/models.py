"""Account models for messenger.

This module defines the User and Block models used for authentication,
identity, and user-to-user blocking.
"""

import uuid
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from .validators import (
    USERNAME_MAX_LENGTH,
    is_reserved_username,
    validate_username_format,
)


class User(AbstractUser):
    """Extended user model for messenger accounts.

    Uses a UUID primary key. Inherits standard auth fields from ``AbstractUser``
    (username, email, password, ``is_active``, ``is_staff``, etc.).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(
        "username",
        max_length=USERNAME_MAX_LENGTH,
        unique=True,
        help_text="3–30 characters. Letters, numbers, and underscore only.",
        validators=[validate_username_format],
        error_messages={
            "unique": "A user with that username already exists.",
            "max_length": "Use %d characters or fewer." % USERNAME_MAX_LENGTH,
        },
    )
    email = models.EmailField("email address", unique=True, null=True, blank=True)
    avatar_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Return the string representation of the user.

        Returns:
            str: The username of the user.
        """
        return self.username

    def save(self, *args, **kwargs):
        """Store a trimmed, lowercased email, or NULL when it is empty.

        Empty strings cannot share a unique column. NULL can, so accounts
        created before email was required do not collide.
        """
        if self.email is not None:
            normalized = self.email.strip().lower()
            self.email = normalized or None
        if self._state.adding and is_reserved_username(self.username or ""):
            raise ValidationError({"username": "This username is reserved."})
        super().save(*args, **kwargs)

    def clean(self):
        """Reject a new account that takes a reserved username.

        An account that already has a reserved name, such as an existing
        ``admin`` user, can still be saved.
        """
        super().clean()
        username = self.username or ""
        if not is_reserved_username(username):
            return
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list(
                "username", flat=True
            ).first()
            if previous and previous.casefold() == username.casefold():
                return
        raise ValidationError({"username": "This username is reserved."})

    def get_full_display_name(self):
        """Return the user's display name with fallback to username.

        Returns:
            str: The user's full name if available, otherwise username.
        """
        full_name = self.get_full_name()
        return full_name if full_name else self.username

    def display_initials(self):
        """Return one or two letters for an avatar that has no image.

        Returns:
            str: Uppercase letters from the username, or ``?`` when it has none.
        """
        letters = [character for character in (self.username or "") if character.isalnum()]
        if not letters:
            return "?"
        if len(letters) == 1:
            return letters[0].upper()
        return (letters[0] + letters[1]).upper()

    def has_avatar(self):
        """Check whether the user has an avatar set.

        Returns:
            bool: True if ``avatar_url`` is defined, otherwise False.
        """
        return bool(self.avatar_url)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['username']
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="accounts_user_username_ci",
            ),
        ]


class Block(models.Model):
    """Represents a unilateral user block between two users.

    A block prevents the ``blocked`` user from sending direct messages
    to the ``blocker``.
    The pair ``(blocker, blocked)`` is unique and indexed for lookups.
    """

    blocker = models.ForeignKey(
        User,
        related_name="blocks_initiated",
        on_delete=models.CASCADE
    )
    blocked = models.ForeignKey(
        User,
        related_name="blocks_received",
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("blocker", "blocked")
        indexes = [
            models.Index(fields=["blocker", "blocked"]),
        ]

    def __str__(self):
        """Return a human-readable representation of the block relation.

        Returns:
            str: A formatted string describing the block.
        """
        return f"{self.blocker} blocked {self.blocked}"
