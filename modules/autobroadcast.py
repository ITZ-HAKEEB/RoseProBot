"""Auto-broadcast: ONE message every 24 hours to every known group and user (each chat only once).

* never right after a restart: the time of the last broadcast is saved in the database, and nothing is sent in
  the first 5 minutes after the bot starts
* text comes from autobroadcast_text.py, or from the owner command /setautobroadcast (the command wins)
* the only button is "Add me to your group"
Owner commands: /setautobroadcast <text>   /autobroadcast on|off   /autobroadcast (status)
"""
import asyncio
import time

from telegram import InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, Forbidden, RetryAfter

import db
from autobroadcast_text import AUTOBROADCAST_TEXT
from config import SUDO
from core import args_text, command, esc, log, register_help, reply, sbtn, send_log

INTERVAL = 24 * 3600
STARTUP_GRACE = 300

register_help('owner', [
    ('setautobroadcast', 'Owner only. Set the daily auto-broadcast text (or reply to a text message)'),
    ('autobroadcast', 'Owner only. /autobroadcast on|off, or no argument for the status'),
])


def current_text():
    return db.get("meta", "ab_text") or AUTOBROADCAST_TEXT


def enabled():
    return db.get("meta", "ab_on", True)


async def run_once(bot):
    """Send the saved text once to every known chat. Returns (sent, removed)."""
    text = current_text()
    kb = Markup([[sbtn("➕ Add me to your group", "success",
                       url=f"https://t.me/{bot.username}?startgroup=true&admin=delete_messages+restrict_members+pin_messages+invite_users")]])
    targets, seen = [], set()
    for scope in ("bc_chats", "bc_users"):
        for k in db.scope_keys(scope):
            if int(k) not in seen:           # never twice to the same chat
                seen.add(int(k))
                targets.append((scope, int(k)))
    ok = removed = 0
    for scope, cid in targets:
        try:
            while True:
                try:
                    await bot.send_message(cid, text, reply_markup=kb)
                    ok += 1
                    break
                except RetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
        except (Forbidden, BadRequest):
            db.delete(scope, cid)            # blocked / kicked / chat gone
            removed += 1
        except Exception as e:
            log.warning("autobroadcast to %s failed: %s", cid, e)
        await asyncio.sleep(0.05)
    return ok, removed


async def loop(bot):
    if db.get("meta", "ab_last") is None:
        db.put("meta", "ab_last", time.time())        # first ever start: the first broadcast is 24h from now
    await asyncio.sleep(STARTUP_GRACE)
    while True:
        try:
            last = db.get("meta", "ab_last", 0) or 0
            if enabled() and current_text() and time.time() - last >= INTERVAL:
                db.put("meta", "ab_last", time.time())   # saved first: a crash mid-send can't cause a repeat
                ok, removed = await run_once(bot)
                await send_log(bot, f"📢 <b>Auto broadcast</b>\nSent: {ok} · Removed: {removed}")
        except Exception:
            log.exception("autobroadcast loop")
        await asyncio.sleep(60)


def start(app):
    """Called once from bot.py post_init."""
    app.create_task(loop(app.bot))


@command("setautobroadcast")
async def cmd_set(update, ctx):
    msg, user = update.effective_message, update.effective_user
    if user.id not in SUDO:
        return
    text = args_text(msg) or (msg.reply_to_message.text_html if msg.reply_to_message and msg.reply_to_message.text else "")
    if not text:
        return await reply(update, "Usage: /setautobroadcast &lt;text&gt; (or reply to a text message). HTML is allowed.")
    db.put("meta", "ab_text", text)
    await reply(update, "✅ Auto-broadcast text saved. It goes out once every 24 hours.")


@command("autobroadcast")
async def cmd_ab(update, ctx):
    user = update.effective_user
    if user.id not in SUDO:
        return
    arg = (ctx.args[0].lower() if ctx.args else "")
    if arg in ("on", "off"):
        db.put("meta", "ab_on", arg == "on")
    last = db.get("meta", "ab_last", 0) or 0
    left = max(0, INTERVAL - (time.time() - last))
    t = current_text()
    await reply(update, f"📢 <b>Auto broadcast</b>: {'ON ✅' if enabled() else 'OFF ❌'}\n"
                        f"Next send in about {int(left // 3600)}h {int(left % 3600 // 60)}m\n"
                        f"Text: {esc(t[:200]) if t else '— not set (use /setautobroadcast)'}")
