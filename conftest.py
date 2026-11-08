"""Shared pytest fixtures for messenger accounts and chat tests."""

import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def user_factory(db):
    """Factory fixture for creating users with custom attributes safely.

    Returns:
        callable: Function that creates and returns a User instance.
            Args:
                username (str): Username for the user.
                password (str): Password for the user. Defaults to 'test123'.
                email (str, optional): Email for the user.
                **kwargs: Additional fields to set on the user.
    """

    counter = {"i": 0}

    def create_user(username=None, password="test123", **kwargs):
        counter["i"] += 1
        if username is None:
            username = f"player{counter['i']}"
        kwargs.setdefault("email", f"{username}@example.com")

        existing_user = User.objects.filter(username=username).first()
        if existing_user:
            return existing_user

        return User.objects.create_user(username=username, password=password, **kwargs)

    return create_user


@pytest.fixture
def test_user(user_factory):
    """Create a default test user.

    Returns:
        User: A user instance with username 'player1'.
    """
    return user_factory(username="player1", email="player1@example.com")


@pytest.fixture
def second_user(user_factory):
    """Create a second test user.

    Returns:
        User: A user instance with username 'player2'.
    """
    return user_factory(username="player2", email="player2@example.com")


@pytest.fixture
def api_client():
    """DRF APIClient for API tests."""
    return APIClient()
