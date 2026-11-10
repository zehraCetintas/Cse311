"""
Helpers for reading settings from environment variables.

Values can be set in the shell or in a `.env` file in the project root
(see `.env.example`). The `.env` file is ignored by git, so secrets never
end up in the repository.
"""

import os

from django.core.exceptions import ImproperlyConfigured

# Only used when DEBUG is on and DJANGO_SECRET_KEY is not set, so that the
# project runs locally without any setup. Never use it in production.
DEV_SECRET_KEY = "django-insecure-local-development-only-do-not-use-in-production"

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    value = value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, got {value!r}.")


def env_list(name, default=()):
    """Comma-separated list, e.g. DJANGO_ALLOWED_HOSTS=example.com,www.example.com"""
    value = os.environ.get(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or list(default)


def secret_key(debug):
    key = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if key:
        return key
    if debug:
        return DEV_SECRET_KEY
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false."
    )
