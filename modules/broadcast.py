"""Owner-only broadcast system.
Default: Groups only.
-user: Groups first, then all users.
-pin: Pin delivered messages where permitted.
Supports text and replied messages.
"""

import asyncio

from telegram.error import Forbidden, BadRequest, RetryAfter

import db
from config import SUDO
from core import (
    args_text,
    command,
    esc,
    log,
    register_help,
    reply,
    send_log,
)


register_help("owner", [
    (
        "broadcast",
        "Owner only. /broadcast [-user] [-pin] <text> or reply to a message."
    ),
])


async def broadcast_to_scope(ctx, scope, pin=False, src=None, text=None):
    """Broadcast to one database scope and return statistics."""

    targets = list(db.scope_keys(scope))

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
                                "Could not pin message in %s: %s",
                                chat_id,
                                pin_error,
                            )

                    break

                except RetryAfter as e:
                    wait_time = (
                        e.retry_after.total_seconds()
                        if hasattr(e.retry_after, "total_seconds")
                        else float(e.retry_after)
                    )
                    await asyncio.sleep(wait_time + 1)

        except (Forbidden, BadRequest) as e:
            failed_count += 1

            try:
                db.delete(scope, key)
            except Exception:
                db.delete(scope, int(key))

            removed_count += 1

            log.warning(
                "Removed inaccessible chat %s: %s",
                key,
                e,
            )

        except Exception as e:
            failed_count += 1

            log.warning(
                "Broadcast failed for %s: %s",
                key,
                e,
            )

        # Telegram rate limit protection
        await asyncio.sleep(0.05)

    return {
        "total": len(targets),
        "sent": sent_count,
        "failed": failed_count,
        "removed": removed_count,
        "pinned": pinned_count,
    }


def broadcast_report(title, stats, pin=False):
    """Create separate group/user broadcast report."""

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

    report += "━━━━━━━━━━━━━━━━━━"

    return report


@command("broadcast")
async def cmd_broadcast(update, ctx):

    msg = update.effective_message
    user = update.effective_user

    # Owner / SUDO protection
    if not user or user.id not in SUDO:
        return

    text = args_text(msg).strip()

    # Default: Groups only
    include_users = False
    pin = False
    include_groups = True

    # Parse flags
    while text.startswith("-"):

        flag, _, rest = text.partition(" ")
        flag = flag.lower()

        if flag in ("-user", "-users"):
            # -user means BOTH groups and users
            include_users = True
            include_groups = True

        elif flag in ("-group", "-groups", "-chats"):
            include_groups = True
            include_users = False

        elif flag == "-all":
            include_groups = True
            include_users = True

        elif flag == "-pin":
            pin = True

        else:
            break

        text = rest.strip()

    # Replied message support
    src = msg.reply_to_message

    if not src and not text:
        return await reply(
            update,
            "❌ <b>Broadcast Usage</b>\n\n"
            "/broadcast <code>text</code> - Groups only\n"
            "/broadcast -user <code>text</code> - Groups + Users\n"
            "/broadcast -pin <code>text</code> - Groups + Pin\n"
            "/broadcast -user -pin <code>text</code> - Groups + Users + Pin\n\n"
            "You can also reply to any message with these commands."
        )

    # Initial status
    group_stats = None
    user_stats = None

    status = await reply(
        update,
        "📢 <b>Broadcast Started</b>\n\n"
        "⏳ Preparing group broadcast..."
    )

    # ==========================================
    # STEP 1: GROUP BROADCAST
    # ==========================================

    if include_groups:

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

        # Show group report BEFORE starting users
        if include_users:
            await status.edit_text(
                group_report
                + "\n\n⏳ <b>Now starting user broadcast...</b>"
            )

        else:
            await status.edit_text(
                group_report
                + "\n\n✅ <b>Broadcast Completed!</b>"
            )

    # ==========================================
    # STEP 2: USER BROADCAST
    # ==========================================

    if include_users:

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

        # Final report with separate group and user results
        final_report = (
            "✅ <b>BROADCAST COMPLETED</b>\n\n"
            + (
                broadcast_report(
                    "📢 GROUP REPORT",
                    group_stats,
                    pin,
                )
                if group_stats else ""
            )
            + "\n\n"
            + user_report
            + "\n\n🎉 <b>All Broadcast Tasks Finished!</b>"
        )

        await status.edit_text(final_report)

    # ==========================================
    # STEP 3: LOG REPORT
    # ==========================================

    group_sent = group_stats["sent"] if group_stats else 0
    user_sent = user_stats["sent"] if user_stats else 0

    group_failed = group_stats["failed"] if group_stats else 0
    user_failed = user_stats["failed"] if user_stats else 0

    log_text = (
        f"📢 <b>Broadcast Completed</b>\n\n"
        f"👤 By: {esc(user.first_name)}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📢 Groups Sent: {group_sent}\n"
        f"👥 Users Sent: {user_sent}\n"
        f"❌ Group Failed: {group_failed}\n"
        f"❌ User Failed: {user_failed}\n"
        f"📌 Pin: {'Enabled' if pin else 'Disabled'}"
    )

    await send_log(ctx.bot, log_text)
