"""Forms for server-rendered chat flows (mirroring REST validation rules)."""

from django import forms


class StartDirectChatForm(forms.Form):
    """Identify another user to open or reuse a 1-on-1 chat."""

    other_username = forms.CharField(
        max_length=150,
        label="Other user's username",
        help_text="Case-insensitive match to an existing account.",
        widget=forms.TextInput(
            attrs={"class": "ui-input", "placeholder": "Username", "autocomplete": "off"}
        ),
    )

    def clean_other_username(self):
        """Return stripped username for lookup."""
        return (self.cleaned_data.get("other_username") or "").strip()


class StartGroupChatForm(forms.Form):
    """Create a named group chat."""

    name = forms.CharField(
        max_length=60,
        min_length=1,
        label="Group name",
        help_text="1–60 characters.",
        widget=forms.TextInput(
            attrs={"class": "ui-input", "placeholder": "Team name", "autocomplete": "off"}
        ),
    )
    description = forms.CharField(
        required=False,
        max_length=500,
        label="Description",
        help_text="Optional. Up to 500 characters.",
        widget=forms.Textarea(
            attrs={
                "class": "ui-input ui-input--textarea",
                "rows": 3,
                "placeholder": "What is this group for?",
            }
        ),
    )
    avatar_url = forms.URLField(
        required=False,
        assume_scheme="https",
        label="Avatar URL",
        help_text="Optional image address.",
        widget=forms.URLInput(
            attrs={"class": "ui-input", "placeholder": "https://"}
        ),
    )

    def clean_name(self):
        """Strip the name; empty after strip is rejected by the field."""
        return " ".join((self.cleaned_data.get("name") or "").split())

    def clean_description(self):
        """Strip the optional description."""
        return (self.cleaned_data.get("description") or "").strip()

    def clean_avatar_url(self):
        """Return a stripped URL or empty string."""
        return (self.cleaned_data.get("avatar_url") or "").strip()


class ChatMessageForm(forms.Form):
    """Post a new message in a chat room (HTTP form, same limits as the API)."""

    content = forms.CharField(
        max_length=10000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Type a message…",
                "class": "ui-input ui-input--textarea",
            }
        ),
    )

    def clean_content(self):
        """Strip whitespace; reject empty after strip."""
        value = (self.cleaned_data.get("content") or "").strip()
        if not value:
            raise forms.ValidationError("Message cannot be empty.")
        return value
