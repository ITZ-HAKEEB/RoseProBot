"""Environment configuration."""
import os

TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ.get("OWNER_ID", "0") or 0)
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/kirti_bots_support")
UPDATES_URL = os.environ.get("UPDATES_URL", "https://t.me/kirti_bots")
SUDO = {OWNER_ID} if OWNER_ID else set()

# Optional: image scanning for the NSFW module (https://sightengine.com, free tier available).
# Without these two the NSFW module still filters text / captions by keywords.
SIGHTENGINE_USER = os.environ.get("SIGHTENGINE_USER", "")
SIGHTENGINE_SECRET = os.environ.get("SIGHTENGINE_SECRET", "")
NSFW_THRESHOLD = float(os.environ.get("NSFW_THRESHOLD", "0.7") or 0.7)
