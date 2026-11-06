"""Environment configuration."""
import os

TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/llNOBI_SUPPORTll")

# "Owner" button on /start: a t.me link. Empty = opens a chat with OWNER_ID.
OWNER_URL = os.environ.get("OWNER_URL", "").strip() or (f"tg://user?id={OWNER_ID}" if OWNER_ID else "8538619965")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/llNOBI_UPDATESll")
SUDO = {OWNER_ID} if OWNER_ID else set()

# Logger: chat/channel id where the bot reports startups, new groups and new users (bot must be admin / member there).
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL_ID", "-1004426372558") or 0)

# NSFW images are scanned locally with NudeNet (no API needed). These two are only an optional fallback
# (https://sightengine.com) used when NudeNet is not installed.
SIGHTENGINE_USER = os.environ.get("SIGHTENGINE_USER", "")
SIGHTENGINE_SECRET = os.environ.get("SIGHTENGINE_SECRET", "")
NSFW_THRESHOLD = float(os.environ.get("NSFW_THRESHOLD", "0.6") or 0.6)


# Photo for the join-request DM: an image URL or a Telegram file_id. Empty = use the bot's own profile picture.
JOIN_PHOTO = os.environ.get("JOIN_PHOTO", "https://ibb.co/prxk9Tpr")

# Small line at the bottom of the bio-link / NSFW cards, linked to UPDATES_URL: "✦ Updates ✦"
FOOTER_TEXT = os.environ.get("FOOTER_TEXT", "Updates")
# Picture on top of the /start message: a direct image URL or a Telegram file_id.
# Empty = the bot's own profile picture is used (and plain text if it has none).
START_IMAGE = os.environ.get("START_IMAGE", "https://ibb.co/prxk9Tpr").strip()


