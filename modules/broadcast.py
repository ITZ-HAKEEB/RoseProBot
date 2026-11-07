"""Owner-only broadcast system.

Default: Groups only.
-user: Groups first, then all users.
-pin: Pin delivered messages where permitted.
Supports text and replied messages.
"""

import asyncio
import re

from telegram.error import Forbidden, BadRequest, RetryAfter

import db
from config import SUDO
from core import (
    esc,
    log,
    register_help,
    reply,
    send_log,
    command,
)


# ==========================================================
# OWNER CONFIGURATION
# ==========================================================

def get_sudo_ids():
    """Convert SUDO IDs into integers safely."""

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


# ==========================================================
# HELP
# ==========================================================

register_help("owner", [
    (
        "broadcast",
        "Owner only. /broadcast [-user] [-pin] <text> or reply to a message."
    ),
])


# ==========================================================
# BROADCAST ENGINE
# ==========================================================

async def broadcast_to_scope(ctx, scope, pin=False, src=None, text=None):

    try:
        targets = list(db.scope_keys(scope))
    except Exception as e:
        log.exception("Could not fetch broadcast targets: %s", e)

        return {
            "total": 0,
            "sent": 0,
            "failed": 0,
            "removed": 0,
            "pinned": 0,
            "error": str(e),
        }

    sent_count = 0
    failed_count = 0
    removed_count = 0
    pinned_count = 0

    for key in targets:

        try:
            chat_id = int(key)

            while True:
                try:

                    if src:
                        sent = await ctx.bot.copy_message(
                            chat_id=chat_id,
                            from_chat_id=src.chat.id,
                            message_id=src.message_id,
                        )

                    else:
                        sent = await ctx.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                        )

                    sent_count += 1

                    # PIN MESSAGE
                    if pin:

                        try:
                            await ctx.bot.pin_chat_message(
                                chat_id=chat_id,
                                message_id=sent.message_id,
                                disable_notification=True,
                            )

                            pinned_count += 1

                        except Exception as pin_error:
                            log.warning(
                                "Pin failed in %s: %s",
                                chat_id,
                                pin_error,
                            )

                    break

                except RetryAfter as e:

                    wait_time = getattr(e, "retry_after", 5)

                    if hasattr(wait_time, "total_seconds"):
                        wait_time = wait_time.total_seconds()

                    wait_time = float(wait_time)

                    log.warning(
                        "Telegram rate limit. Waiting %.2f seconds",
                        wait_time,
                    )

                    await asyncio.sleep(wait_time + 1)

        except (Forbidden, BadRequest) as e:

            failed_count += 1

            # Remove inaccessible users/groups
            try:
                db.delete(scope, key)
                removed_count += 1

            except Exception as delete_error:
                log.warning(
                    "Database removal failed for %s: %s",
                    key,
                    delete_error,
                )

            log.warning(
                "Broadcast target unavailable %s: %s",
                key,
                e,
            )

        except Exception as e:

            failed_count += 1

            log.exception(
                "Broadcast failed for %s: %s",
                key,
                e,
            )

        # Rate-limit protection
        await asyncio.sleep(0.05)

    return {
        "total": len(targets),
        "sent": sent_count,
        "failed": failed_count,
        "removed": removed_count,
        "pinned": pinned_count,
    }


# ==========================================================
# REPORT GENERATOR
# ==========================================================

def broadcast_report(title, stats, pin=False):

    report = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Total: {stats['total']}\n"
        f"✅ Sent: {stats['sent']}\n"
        f"❌ Failed: {stats['failed']}\n"
        f"🗑 Removed: {stats['removed']}\n"
    )

    if pin:
        report += f"📌 Pinned: {stats['pinned']}\n"

    if stats.get("error"):
        report += f"\n⚠️ Error: {esc(stats['error'])}\n"

    report += "━━━━━━━━━━━━━━━━━━"

    return report


# ==========================================================
# COMMAND ARGUMENT PARSER
# ==========================================================

def parse_broadcast_args(msg):

    raw = msg.text or msg.caption or ""

    # Remove /broadcast and optional @botusername
    parts = raw.split(maxsplit=1)

    text = parts[1].strip() if len(parts) > 1 else ""

    include_users = False
    include_groups = True
    pin = False

    # Parse flags
    while text:

        match = re.match(r"^(-[a-zA-Z]+)(?:\s+|$)", text)

        if not match:
            break

        flag = match.group(1).lower()
        text = text[match.end():].strip()

        if flag in ("-user", "-users", "-all"):
            include_users = True
            include_groups = True

        elif flag in ("-group", "-groups", "-chats"):
            include_groups = True
            include_users = False

        elif flag == "-pin":
            pin = True

        else:
            # Unknown flag: preserve remaining text
            text = flag + " " + text
            break

    return text, include_groups, include_users, pin


# ==========================================================
# BROADCAST COMMAND
# ==========================================================

@command("broadcast")
async def cmd_broadcast(update, ctx):

    msg = update.effective_message
    user = update.effective_user

    # ==========================================
    # OWNER CHECK
    # ==========================================

    if not user:
        return

    if user.id not in get_sudo_ids():

        return await reply(
            update,
            "❌ <b>You are not authorized to use this command.</b>"
        )

    # ==========================================
    # PARSE ARGUMENTS
    # ==========================================

    text, include_groups, include_users, pin = (
        parse_broadcast_args(msg)
    )

    # Replied message support
    src = msg.reply_to_message

    if not src and not text:

        return await reply(
            update,
            "❌ <b>Broadcast Usage</b>\n\n"
            "📢 <code>/broadcast Your message</code>\n"
            "👥 <code>/broadcast -user Your message</code>\n"
            "📌 <code>/broadcast -pin Your message</code>\n"
            "🔥 <code>/broadcast -user -pin Your message</code>\n\n"
            "<b>Reply Method:</b>\n"
            "Reply to any message with:\n"
            "<code>/broadcast -user</code>\n\n"
            "Default broadcast: Groups only."
        )

    # ==========================================
    # START STATUS
    # ==========================================

    try:

        status = await reply(
            update,
            "📢 <b>BROADCAST STARTED</b>\n\n"
            "⚙️ Preparing broadcast...\n"
            "⏳ Please wait."
        )

    except Exception as e:

        log.exception("Could not send broadcast status: %s", e)
        return

    group_stats = None
    user_stats = None

    # ==========================================
    # STEP 1: GROUP BROADCAST
    # ==========================================

    if include_groups:

        try:

            await status.edit_text(
                "📢 <b>GROUP BROADCAST</b>\n\n"
                "⏳ Sending messages to groups..."
            )

            group_stats = await broadcast_to_scope(
                ctx=ctx,
                scope="bc_chats",
                pin=pin,
                src=src,
                text=text,
            )

            group_report = broadcast_report(
                "📢 GROUP BROADCAST COMPLETED",
                group_stats,
                pin,
            )

            if include_users:

                await status.edit_text(
                    group_report
                    + "\n\n⏳ <b>Now starting user broadcast...</b>"
                )

            else:

                await status.edit_text(
                    group_report
                    + "\n\n✅ <b>BROADCAST COMPLETED!</b>"
                )

        except Exception as e:

            log.exception("Group broadcast error: %s", e)

            await status.edit_text(
                "❌ <b>Group broadcast error</b>\n\n"
                f"<code>{esc(str(e))}</code>"
            )

    # ==========================================
    # STEP 2: USER BROADCAST
    # ==========================================

    if include_users:

        try:

            await status.edit_text(
                (
                    broadcast_report(
                        "📢 GROUP REPORT",
                        group_stats,
                        pin,
                    )
                    if group_stats else
                    "📢 <b>Group broadcast skipped.</b>"
                )
                + "\n\n👥 <b>USER BROADCAST STARTED</b>\n"
                "⏳ Sending messages to users..."
            )

            user_stats = await broadcast_to_scope(
                ctx=ctx,
                scope="bc_users",
                pin=pin,
                src=src,
                text=text,
            )

            user_report = broadcast_report(
                "👤 USER BROADCAST COMPLETED",
                user_stats,
                pin,
            )

            # ==================================
            # FINAL REPORT
            # ==================================

            final_report = (
                "✅ <b>BROADCAST COMPLETED</b>\n\n"
                + (
                    broadcast_report(
                        "📢 GROUP REPORT",
                        group_stats,
                        pin,
                    )
                    if group_stats else
                    "📢 <b>GROUP REPORT</b>\nNot executed."
                )
                + "\n\n"
                + user_report
                + "\n\n🎉 <b>ALL BROADCAST TASKS FINISHED!</b>"
            )

            await status.edit_text(final_report)

        except Exception as e:

            log.exception("User broadcast error: %s", e)

            try:
                await status.edit_text(
                    "❌ <b>User broadcast error</b>\n\n"
                    f"<code>{esc(str(e))}</code>"
                )
            except Exception:
                pass

    # ==========================================
    # STEP 3: LOG REPORT
    # ==========================================

    group_sent = group_stats["sent"] if group_stats else 0
    user_sent = user_stats["sent"] if user_stats else 0

    group_failed = group_stats["failed"] if group_stats else 0
    user_failed = user_stats["failed"] if user_stats else 0

    log_text = (
        "📢 <b>Broadcast Completed</b>\n\n"
        f"👤 By: {esc(user.first_name)}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📢 Groups Sent: {group_sent}\n"
        f"👥 Users Sent: {user_sent}\n"
        f"❌ Group Failed: {group_failed}\n"
        f"❌ User Failed: {user_failed}\n"
        f"📌 Pin: {'Enabled' if pin else 'Disabled'}"
    )

    try:
        await send_log(ctx.bot, log_text)

    except Exception as e:
        log.exception("Broadcast log failed: %s", e)
