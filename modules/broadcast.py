"""Owner-only /broadcast: send a message to every known user and/or group."""
import asyncio

from telegram.error import Forbidden, BadRequest, RetryAfter

import db
from config import SUDO
from core import args_text, command, esc, log, register_help, reply, send_log

register_help('owner', [
    ('broadcast', 'Owner only. /broadcast [-users|-groups] [-pin] &lt;text&gt; or reply to a message. -pin also pins it in the chats'),
])


@command("broadcast")
async def cmd_broadcast(update, ctx):
    msg, user = update.effective_message, update.effective_user
    if user.id not in SUDO:
        return
    text = args_text(msg)
    mode, pin = "all", False
    while text.startswith("-"):                    # flags in any order: -users/-user, -groups/-group, -all, -pin
        flag, _, rest = text.partition(" ")
        flag = flag.lower()
        if flag in ("-users", "-user"):
            mode = "users"
        elif flag in ("-groups", "-group", "-chats"):
            mode = "groups"
        elif flag == "-all":
            mode = "all"
        elif flag == "-pin":
            pin = True
        else:
            break
        text = rest.strip()
    src = msg.reply_to_message
    if not src and not text:
        return await reply(update, "Usage: /broadcast [-users|-groups|-all] [-pin] &lt;text&gt;, or reply to a message with /broadcast.")

    targets = []
    if mode in ("all", "users"):
        targets += [("bc_users", int(k)) for k in db.scope_keys("bc_users")]
    if mode in ("all", "groups"):
        targets += [("bc_chats", int(k)) for k in db.scope_keys("bc_chats")]
    status = await reply(update, f"📢 Broadcasting to {len(targets)} chats…")

    ok = failed = removed = pinned = 0
    for scope, cid in targets:
        try:
            while True:
                try:
                    if src:
                        sent = await ctx.bot.copy_message(cid, src.chat.id, src.message_id)
                    else:
                        sent = await ctx.bot.send_message(cid, text)
                    ok += 1
                    if pin:
                        try:
                            await ctx.bot.pin_chat_message(cid, sent.message_id, disable_notification=True)
                            pinned += 1
                        except Exception:         # no pin right in that group: the message is still delivered
                            pass
                    break
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
        except (Forbidden, BadRequest):
            failed += 1
            db.delete(scope, cid)     # blocked / kicked / chat gone: stop sending there
            removed += 1
        except Exception as e:
            failed += 1
            log.warning("broadcast to %s failed: %s", cid, e)
        await asyncio.sleep(0.05)     # stay under Telegram's ~30 msgs/sec limit

    done = (f"✅ <b>Broadcast done</b>\nMode: {mode}{' + pin' if pin else ''}\nSent: {ok}\n"
            + (f"Pinned: {pinned}\n" if pin else "")
            + f"Failed: {failed} (removed from list: {removed})")
    await status.edit_text(done)
    await send_log(ctx.bot, f"📢 <b>Broadcast</b> by {esc(user.first_name)} ({user.id})\nMode: {mode} · Sent: {ok} · Failed: {failed}")
