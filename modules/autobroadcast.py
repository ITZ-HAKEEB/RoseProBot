"""Auto-broadcast system.

- One broadcast every 24 hours.
- Every known group and user, only once per run.
- 5-minute startup grace period.
- Last broadcast timestamp saved in database.
- Owner text overrides autobroadcast_text.py.
- Only one button: Add me to your group.

Owner commands:
    /setautobroadcast <text>
    /autobroadcast on
    /autobroadcast off
    /autobroadcast
"""

import asyncio
import time

from telegram import InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, Forbidden, RetryAfter

import db
from autobroadcast_text import AUTOBROADCAST_TEXT
from config import SUDO
from core import (
    args_text,
    command,
    esc,
    log,
    register_help,
    reply,
    sbtn,
    send_log,
)


# ==========================================================
# SETTINGS
# ==========================================================

INTERVAL = 24 * 60 * 60
STARTUP_GRACE = 5 * 60
CHECK_INTERVAL = 60

META_SCOPE = "meta"

# Prevent multiple scheduler instances in the same process.
_TASK_STARTED = False


# ==========================================================
# OWNER CHECK
# ==========================================================

def get_sudo_ids():
    """Safely convert SUDO IDs to integers."""

    if isinstance(SUDO, (str, int)):
        values = str(SUDO).replace(",", " ").split()
    else:
        values = SUDO or []

    result = set()

    for value in values:
        try:
            result.add(int(value))
        except (ValueError, TypeError):
            continue

    return result


def is_owner(user):
    return bool(user and user.id in get_sudo_ids())


# ==========================================================
# HELP
# ==========================================================

register_help("owner", [
    (
        "setautobroadcast",
        "Owner only. Set daily auto-broadcast text. Reply to a text message also supported."
    ),
    (
        "autobroadcast",
        "Owner only. /autobroadcast on|off or /autobroadcast for status."
    ),
])


# ==========================================================
# DATABASE SETTINGS
# ==========================================================

def current_text():
    """Owner custom text has priority over default text."""

    saved = db.get(META_SCOPE, "ab_text")

    if saved and str(saved).strip():
        return str(saved)

    return AUTOBROADCAST_TEXT or ""


def enabled():
    """Read auto-broadcast enabled state safely."""

    value = db.get(META_SCOPE, "ab_on", True)

    if isinstance(value, str):
        return value.strip().lower() in (
            "true", "1", "yes", "on"
        )

    return bool(value)


def get_last_broadcast():
    value = db.get(META_SCOPE, "ab_last", 0) or 0

    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ==========================================================
# KEYBOARD
# ==========================================================

def get_keyboard(bot):

    username = getattr(bot, "username", None)

    if not username:
        return None

    url = (
        f"https://t.me/{username}"
        "?startgroup=true"
        "&admin=delete_messages+restrict_members"
        "+pin_messages+invite_users"
    )

    return Markup([
        [
            sbtn(
                "➕ Add me to your group",
                "success",
                url=url,
            )
        ]
    ])


# ==========================================================
# TARGET COLLECTION
# ==========================================================

def get_targets():
    """Collect unique groups and users."""

    targets = []
    seen = set()

    for scope in ("bc_chats", "bc_users"):

        try:
            keys = list(db.scope_keys(scope))
        except Exception:
            log.exception(
                "Could not load auto-broadcast scope: %s",
                scope,
            )
            continue

        for key in keys:

            try:
                chat_id = int(key)
            except (ValueError, TypeError):
                log.warning("Invalid broadcast target: %s", key)
                continue

            if chat_id in seen:
                continue

            seen.add(chat_id)
            targets.append((scope, chat_id))

    return targets


# ==========================================================
# RETRY HELPER
# ==========================================================

def retry_seconds(error):

    value = getattr(error, "retry_after", 5)

    if hasattr(value, "total_seconds"):
        value = value.total_seconds()

    try:
        return max(1, float(value))
    except (ValueError, TypeError):
        return 5


# ==========================================================
# AUTO BROADCAST ENGINE
# ==========================================================

async def run_once(bot):
    """Send one message to every unique known chat."""

    text = current_text()

    if not text or not text.strip():
        log.warning("Auto-broadcast skipped: message is empty.")
        return 0, 0, 0

    keyboard = get_keyboard(bot)
    targets = get_targets()

    sent_count = 0
    failed_count = 0
    removed_count = 0

    log.info(
        "Auto-broadcast started. Total targets: %s",
        len(targets),
    )

    for scope, chat_id in targets:

        try:

            while True:

                try:

                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )

                    sent_count += 1

                    break

                except RetryAfter as error:

                    wait = retry_seconds(error)

                    log.warning(
                        "Auto-broadcast rate limited. "
                        "Waiting %s seconds.",
                        wait,
                    )

                    await asyncio.sleep(wait + 1)

        except (Forbidden, BadRequest) as error:

            failed_count += 1

            # Remove inaccessible targets.
            try:
                db.delete(scope, chat_id)
                removed_count += 1

            except Exception:
                log.exception(
                    "Could not remove target %s from %s",
                    chat_id,
                    scope,
                )

            log.warning(
                "Auto-broadcast target removed: %s (%s)",
                chat_id,
                error,
            )

        except Exception as error:

            failed_count += 1

            log.exception(
                "Auto-broadcast failed for %s: %s",
                chat_id,
                error,
            )

        # Telegram rate protection.
        await asyncio.sleep(0.05)

    log.info(
        "Auto-broadcast finished. Sent: %s | Failed: %s | Removed: %s",
        sent_count,
        failed_count,
        removed_count,
    )

    return sent_count, failed_count, removed_count


# ==========================================================
# SCHEDULER
# ==========================================================

async def loop(bot):

    log.info("Auto-broadcast scheduler started.")

    # First-ever start: wait a full 24 hours.
    if db.get(META_SCOPE, "ab_last") is None:

        db.put(
            META_SCOPE,
            "ab_last",
            time.time(),
        )

        log.info(
            "First startup detected. First broadcast scheduled after 24 hours."
        )

    # Never broadcast immediately after restart.
    log.info(
        "Auto-broadcast startup grace: %s seconds.",
        STARTUP_GRACE,
    )

    await asyncio.sleep(STARTUP_GRACE)

    while True:

        try:

            if not enabled():
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            text = current_text()

            if not text or not text.strip():
                log.warning(
                    "Auto-broadcast enabled but no message is configured."
                )

                await asyncio.sleep(CHECK_INTERVAL)
                continue

            last = get_last_broadcast()
            now = time.time()

            if now - last >= INTERVAL:

                log.info("24-hour interval completed. Starting broadcast.")

                # Save timestamp BEFORE sending to avoid duplicate
                # broadcasts if the process crashes midway.
                db.put(
                    META_SCOPE,
                    "ab_last",
                    now,
                )

                sent, failed, removed = await run_once(bot)

                report = (
                    "📢 <b>AUTO BROADCAST COMPLETED</b>\n\n"
                    f"✅ Sent: {sent}\n"
                    f"❌ Failed: {failed}\n"
                    f"🗑 Removed: {removed}\n"
                    f"📊 Total: {sent + failed}"
                )

                try:
                    await send_log(bot, report)

                except Exception:
                    log.exception(
                        "Could not send auto-broadcast log."
                    )

        except asyncio.CancelledError:
            log.info("Auto-broadcast scheduler stopped.")
            raise

        except Exception:
            log.exception("Auto-broadcast scheduler error.")

        await asyncio.sleep(CHECK_INTERVAL)


# ==========================================================
# START SCHEDULER
# ==========================================================

def start(app):
    """Call once from bot.py post_init."""

    global _TASK_STARTED

    if _TASK_STARTED:
        log.warning(
            "Auto-broadcast scheduler already started."
        )
        return

    _TASK_STARTED = True

    app.create_task(
        loop(app.bot),
        name="auto-broadcast-loop",
    )

    log.info("Auto-broadcast background task created.")


# ==========================================================
# SET AUTO-BROADCAST TEXT
# ==========================================================

@command("setautobroadcast")
async def cmd_set(update, ctx):

    msg = update.effective_message
    user = update.effective_user

    if not is_owner(user):
        return

    text = args_text(msg).strip()

    # Reply support: text or caption.
    if not text and msg.reply_to_message:

        source = msg.reply_to_message

        text = (
            source.text_html
            if source.text
            else source.caption_html
            if source.caption
            else ""
        )

    if not text:

        return await reply(
            update,
            "❌ <b>Auto-Broadcast Text Missing</b>\n\n"
            "Usage:\n"
            "<code>/setautobroadcast Your message</code>\n\n"
            "You can also reply to a text message."
        )

    try:

        db.put(
            META_SCOPE,
            "ab_text",
            text,
        )

        await reply(
            update,
            "✅ <b>Auto-Broadcast Text Saved!</b>\n\n"
            "Your custom message will now be used "
            "instead of autobroadcast_text.py.\n\n"
            "⏰ Frequency: Every 24 hours."
        )

    except Exception as error:

        log.exception("Could not save auto-broadcast text.")

        await reply(
            update,
            "❌ <b>Could not save message.</b>\n\n"
            f"<code>{esc(str(error))}</code>"
        )


# ==========================================================
# ON / OFF / STATUS COMMAND
# ==========================================================

@command("autobroadcast")
async def cmd_ab(update, ctx):

    user = update.effective_user

    if not is_owner(user):
        return

    args = getattr(ctx, "args", []) or []

    arg = args[0].lower() if args else ""

    # ==========================================
    # ENABLE / DISABLE
    # ==========================================

    if arg in ("on", "off"):

        state = arg == "on"

        try:

            db.put(
                META_SCOPE,
                "ab_on",
                state,
            )

            await reply(
                update,
                (
                    "✅ <b>Auto-Broadcast Enabled!</b>"
                    if state
                    else
                    "❌ <b>Auto-Broadcast Disabled!</b>"
                )
                + "\n\nUse <code>/autobroadcast</code> "
                "to check status."
            )

        except Exception as error:

            log.exception("Could not update auto-broadcast state.")

            return await reply(
                update,
                "❌ <b>Database Error</b>\n\n"
                f"<code>{esc(str(error))}</code>"
            )

    elif arg:

        return await reply(
            update,
            "❌ <b>Invalid Option</b>\n\n"
            "Use:\n"
            "<code>/autobroadcast on</code>\n"
            "<code>/autobroadcast off</code>"
        )

    # ==========================================
    # STATUS
    # ==========================================

    last = get_last_broadcast()

    elapsed = max(0, time.time() - last)
    remaining = max(0, INTERVAL - elapsed)

    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)

    message = current_text()

    status = (
        "📢 <b>AUTO-BROADCAST STATUS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"⚙️ Status: {'ON ✅' if enabled() else 'OFF ❌'}\n"
        f"⏰ Interval: 24 Hours\n"
        f"🕒 Next send: {hours}h {minutes}m\n"
        f"🛡 Startup delay: 5 Minutes\n\n"
        "<b>Message Preview:</b>\n"
        f"{esc(message[:200]) if message else 'Not configured'}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>Commands:</b>\n"
        "<code>/autobroadcast on</code>\n"
        "<code>/autobroadcast off</code>\n"
        "<code>/setautobroadcast Your Text</code>"
    )

    await reply(update, message)
