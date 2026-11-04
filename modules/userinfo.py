"""User / info commands: about, admins, bug, chatinfo, id, ping, kickme, lang, userinfo (+ activity tracking)."""
import os
import time

from telegram.constants import ChatType

import db
from config import OWNER_ID
from core import (args_text, command, esc, fmt_time, is_admin, mention, now, register_help, reply,
                  resolve_user, target, watcher)

register_help('user', [
    ('about', 'About this bot'),
    ('admins', 'List the chat administrators'),
    ('bug', 'Report a bug of this bot: reply to the message that shows it and/or describe it after the command'),
    ('chatinfo', 'Information about this chat'),
    ('connect', 'Manage a group from a private chat: send /connect in the group (admins), or /connect &lt;chat id&gt; here'),
    ('connections', 'Show the groups you are connected to and pick the one your settings commands change'),
    ('disabled', 'List the commands disabled in this chat'),
    ('disconnect', 'End a connection (in the group: this group; in private: the selected one, a chat id, or "all")'),
    ('help', 'List commands you can use'),
    ('id', 'Show user and chat ids'),
    ('kickme', 'Leave this group: the bot removes you (you can rejoin)'),
    ('lang', 'Show or change the language (in a group: admins only; in private: just for you)'),
    ('ping', 'Check that the bot is alive and how fast it answers'),
    ('rules', 'Show the chat rules (by default as a button that opens them in a private chat with the bot)'),
    ('start', 'Start the bot'),
    ('userinfo', 'Profile and activity of a user'),
    ('warns', 'Show active warnings (yours, or of a user if you are an admin)'),
    ('warnsettings', "Show this chat's warn limit, action and expiry"),
])


@command("about")
async def cmd_about(update, ctx):
    await reply(update, f"<b>{esc(ctx.bot.first_name)}</b>\nA group management bot: federations, filters, locks, notes, "
                        "reports, warnings, welcome messages, bio-link and NSFW filters and moderation.\nUse /help to see every command.")


@command("admins")
async def cmd_admins(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        c = await target(update, ctx, admin=False)
        if not c:
            return
        chat = c
    adms = await ctx.bot.get_chat_administrators(chat.id)
    lines = [f"<b>Admins in {esc(chat.title)}</b>", ""]
    for a in adms:
        if a.user.is_bot:
            continue
        star = "👑 " if a.status == "creator" else "• "
        lines.append(star + mention(a.user.id, a.user.first_name))
    await reply(update, "\n".join(lines))


@command("bug")
async def cmd_bug(update, ctx):
    msg, user = update.effective_message, update.effective_user
    txt = args_text(msg)
    if not txt and not msg.reply_to_message:
        return await reply(update, "Describe the bug after the command, or reply to the message that shows it.")
    dest = int(os.environ.get("BUG_CHAT_ID", "0") or 0) or OWNER_ID
    if dest:
        body = f"🐞 <b>Bug report</b> from {mention(user.id, user.first_name)} (<code>{user.id}</code>)\n\n{esc(txt)}"
        await ctx.bot.send_message(dest, body)
        if msg.reply_to_message:
            await msg.reply_to_message.forward(dest)
    await reply(update, "Thanks! Your report was sent to the bot owner.")


@command("chatinfo")
async def cmd_chatinfo(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        c = await target(update, ctx, admin=False)
        if not c:
            return
        chat = c
    n = await ctx.bot.get_chat_member_count(chat.id)
    adms = await ctx.bot.get_chat_administrators(chat.id)
    fed = db.get(f"c:{chat.id}", "fed")
    fname = (db.get("fed", fed) or {}).get("name") if fed else None
    await reply(update, f"<b>{esc(chat.title)}</b>\nID: <code>{chat.id}</code>\nType: {chat.type}\n"
                        f"Members: {n}\nAdmins: {len(adms)}\nFederation: {esc(fname) if fname else 'none'}")


@command("id")
async def cmd_id(update, ctx):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    lines = []
    if msg.reply_to_message and msg.reply_to_message.from_user:
        lines.append(f"Replied user ID: <code>{msg.reply_to_message.from_user.id}</code>")
    lines.append(f"Your ID: <code>{user.id}</code>")
    if chat.type != ChatType.PRIVATE:
        lines.append(f"Chat ID: <code>{chat.id}</code>")
    await reply(update, "\n".join(lines))


@command("ping")
async def cmd_ping(update, ctx):
    t = time.monotonic()
    m = await reply(update, "Pong…")
    await m.edit_text(f"🏓 Pong! <code>{(time.monotonic() - t) * 1000:.0f} ms</code>")


@command("kickme")
async def cmd_kickme(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == ChatType.PRIVATE:
        return await reply(update, "This works in groups only.")
    if await is_admin(chat, user.id, ctx):
        return await reply(update, "I can't remove an admin.")
    await ctx.bot.ban_chat_member(chat.id, user.id)
    await ctx.bot.unban_chat_member(chat.id, user.id)
    await reply(update, "Done, you can rejoin any time.")


LANGS = {"en": "English", "hi": "Hindi"}


@command("lang")
async def cmd_lang(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    scope, key = (f"u:{user.id}", "lang") if chat.type == ChatType.PRIVATE else (f"c:{chat.id}", "lang")
    if ctx.args:
        if chat.type != ChatType.PRIVATE and not await is_admin(chat, user.id, ctx):
            return await reply(update, "Only admins can change the group language.")
        code = ctx.args[0].lower()
        if code not in LANGS:
            return await reply(update, "Available: " + ", ".join(f"<code>{k}</code> ({v})" for k, v in LANGS.items()))
        db.put(scope, key, code)
        return await reply(update, f"Language set to {LANGS[code]}.")
    cur = db.get(scope, key, "en")
    await reply(update, f"Current language: {LANGS[cur]}\nChange with /lang &lt;code&gt;: " + ", ".join(LANGS))


@command("userinfo")
async def cmd_userinfo(update, ctx):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if msg.reply_to_message or ctx.args:
        r = await resolve_user(update, ctx, ctx.args)
        if not r:
            return
        uid = r[0]
    else:
        uid = user.id
    try:
        u = await ctx.bot.get_chat(uid)
    except Exception:
        u = None
    lines = [f"<b>User info</b>", f"ID: <code>{uid}</code>"]
    if u:
        lines.append(f"Name: {esc(u.full_name)}")
        if u.username:
            lines.append(f"Username: @{esc(u.username)}")
    lines.append(f"Link: {mention(uid, 'profile')}")
    if chat.type != ChatType.PRIVATE:
        st = db.get(f"s:{chat.id}", uid)
        if st:
            lines.append(f"Messages here: {st['n']}")
            lines.append(f"First seen: {fmt_time(st['first'])}")
        try:
            m = await ctx.bot.get_chat_member(chat.id, uid)
            lines.append(f"Status: {m.status}")
        except Exception:
            pass
        fed = db.get(f"c:{chat.id}", "fed")
        if fed:
            f = db.get("fed", fed)
            if f and str(uid) in f["bans"]:
                lines.append("🚫 Federation banned: " + esc(f["bans"][str(uid)].get("reason", "")))
    await reply(update, "\n".join(lines))


@watcher(10)
async def track_users(update, ctx):
    """Remember @usernames and per-chat message counts (feeds /userinfo and @username lookups)."""
    chat, user = update.effective_chat, update.effective_user
    if user.username:
        db.put("usernames", user.username.lower(), user.id)
    st = db.get(f"s:{chat.id}", user.id) or {"n": 0, "first": now()}
    st["n"] += 1
    db.put(f"s:{chat.id}", user.id, st)
