"""Deployment checks for account settings."""

from django.conf import settings
from django.core.checks import Error, register


@register()
def check_email_confirmation_required(app_configs, **kwargs):
    """Fail the deploy check when confirmation is off outside local debug.

    ``ACCOUNT_EMAIL_CONFIRMATION_REQUIRED=False`` is only for local
    testing. A production process (``DEBUG`` is false) must not boot
    with that switch off. Settings also refuse to import in that case.

    Args:
        app_configs: Apps selected for this check run. Unused.
        **kwargs: Check framework options. Unused.

    Returns:
        list[Error]: One error when the switch is unsafe, else empty.
    """
    del app_configs, kwargs
    if settings.DEBUG or settings.ACCOUNT_EMAIL_CONFIRMATION_REQUIRED:
        return []
    return [
        Error(
            "ACCOUNT_EMAIL_CONFIRMATION_REQUIRED is disabled while DEBUG is False.",
            hint="Set ACCOUNT_EMAIL_CONFIRMATION_REQUIRED=True in production.",
            id="accounts.E001",
        )
    ]


@register()
def check_allowed_hosts(app_configs, **kwargs):
    """Fail the deploy check when production has no ALLOWED_HOSTS.

    Args:
        app_configs: Apps selected for this check run. Unused.
        **kwargs: Check framework options. Unused.

    Returns:
        list[Error]: One error when the host list is empty in production.
    """
    del app_configs, kwargs
    hosts = [host for host in settings.ALLOWED_HOSTS if host]
    if settings.DEBUG or hosts:
        return []
    return [
        Error(
            "ALLOWED_HOSTS is empty while DEBUG is False.",
            hint="Set ALLOWED_HOSTS to the public host names of this deploy.",
            id="accounts.E002",
        )
    ]
