"""Feature modules.

Importing a module registers its commands, help section,
callbacks and watchers in core.py.

Import order is kept as registration order.
"""

from . import (  # noqa: F401

    # Basic commands
    help,
    userinfo,
    connections,
    rules,

    # Moderation
    moderation,
    warns,
    federation,
    keyword_filters,
    locks,

    # Group features
    notes,
    reports,
    welcome,
    biolink,
    nsfw,

    # Broadcast features
    broadcast,
    autobroadcast,
)
