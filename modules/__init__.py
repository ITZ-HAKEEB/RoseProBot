"""Feature modules. Importing a module registers its commands, help section and watchers (see core.py)."""
from . import (  # noqa: F401  (import order = registration order)
    help,
    userinfo,
    connections,
    rules,
    moderation,
    warns,
    federation,
    keyword_filters,
    locks,
    notes,
    reports,
    welcome,
    biolink,
    nsfw,
)
