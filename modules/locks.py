"""Locks: block message types from non-admins."""
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

import db
from core import callback, command, esc, is_admin, join_hook, register_help, reply, target, watcher

register_help('locks', [
    ('lock', 'Lock a type: /lock &lt;type&gt;'),
    ('locks', 'Show which message types are locked'),
    ('locktype', 'See every lock type and what it blocks (tap a button)'),
    ('unlock', 'Unlock a type: /unlock &lt;type&gt;'),
])


LOCKS = {
    "audio": "audio files", "bots": "adding bots (by non-admins)", "button": "messages with inline buttons",
    "command": "bot commands", "contact": "shared contacts", "document": "files / documents",
    "email": "email addresses", "forward": "forwarded messages", "game": "games", "gif": "GIFs / animations",
    "inline": "messages sent via inline bots", "invitelink": "Telegram invite links", "location": "locations / venues",
    "phone": "phone numbers", "photo": "photos", "poll": "polls", "rtl": "right-to-left text (Arabic/Hebrew)",
    "sticker": "stickers", "text": "plain text messages", "url": "links / urls", "video": "videos",
    "videonote": "round video notes", "voice": "voice messages", "all": "everything from non-admins",
}
RTL_RE = re.compile(r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F]")
INVITE_RE = re.compile(r"(t\.me/(joinchat|\+)|telegram\.me/joinchat)", re.I)


def violations(msg):
    v = {"all"}
    ents = list(msg.entities or []) + list(msg.caption_entities or [])
    types = {e.type for e in ents}
    txt = msg.text or msg.caption or ""
    if msg.audio: v.add("audio")
    if msg.reply_markup and getattr(msg.reply_markup, "inline_keyboard", None): v.add("button")
    if "bot_command" in types: v.add("command")
    if msg.contact: v.add("contact")
    if msg.document and not msg.animation: v.add("document")
    if "email" in types: v.add("email")
    if msg.forward_origin: v.add("forward")
    if msg.game: v.add("game")
    if msg.animation: v.add("gif")
    if msg.via_bot: v.add("inline")
    if INVITE_RE.search(txt) or any(e.type == "text_link" and INVITE_RE.search(e.url or "") for e in ents): v.add("invitelink")
    if msg.location or msg.venue: v.add("location")
    if "phone_number" in types: v.add("phone")
    if msg.photo: v.add("photo")
    if msg.poll: v.add("poll")
    if RTL_RE.search(txt): v.add("rtl")
    if msg.sticker: v.add("sticker")
    if msg.text and "bot_command" not in types: v.add("text")
    if types & {"url", "text_link"}: v.add("url")
    if msg.video: v.add("video")
    if msg.video_note: v.add("videonote")
    if msg.voice: v.add("voice")
    return v


@command("locks")
async def cmd_locks(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    locked = set(db.get(f"c:{chat.id}", "locks", []))
    lines = [f"<b>Locks in {esc(chat.title)}</b>", ""]
    lines += [f"{'🔒' if k in locked else '🔓'} {k}" for k in LOCKS]
    await reply(update, "\n".join(lines))


@command("locktype", "locktypes")
async def cmd_locktype(update, ctx):
    names = list(LOCKS)
    rows = [[Btn(n, callback_data=f"lt:{n}") for n in names[i:i + 3]] for i in range(0, len(names), 3)]
    await reply(update, "Lock types — tap one to see what it blocks:", reply_markup=Markup(rows))


@callback(r"^lt:")
async def lt_cb(update, ctx):
    q = update.callback_query
    n = q.data.split(":", 1)[1]
    await q.answer(f"{n}: blocks {LOCKS[n]}", show_alert=True)


@command("lock")
async def cmd_lock(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    bad = [a for a in ctx.args if a.lower() not in LOCKS]
    if not ctx.args or bad:
        return await reply(update, "Usage: /lock &lt;type&gt;. See /locktype for the list.")
    cur = set(db.get(f"c:{chat.id}", "locks", []))
    cur |= {a.lower() for a in ctx.args}
    db.put(f"c:{chat.id}", "locks", sorted(cur))
    await reply(update, "🔒 Locked: " + ", ".join(a.lower() for a in ctx.args))


@command("unlock")
async def cmd_unlock(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args:
        return await reply(update, "Usage: /unlock &lt;type&gt;")
    cur = set(db.get(f"c:{chat.id}", "locks", []))
    cur -= {a.lower() for a in ctx.args}
    db.put(f"c:{chat.id}", "locks", sorted(cur))
    await reply(update, "🔓 Unlocked: " + ", ".join(a.lower() for a in ctx.args))


@join_hook(20)
async def bots_lock_join(update, ctx, u, adder_admin):
    chat = update.effective_chat
    locks = set(db.get(f"c:{chat.id}", "locks", []))
    if u.is_bot and "bots" in locks and not adder_admin and u.id != ctx.bot.id:
        try:
            await ctx.bot.ban_chat_member(chat.id, u.id)
        except Exception:
            pass
        return True


@watcher(30)
async def lock_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    locked = set(db.get(f"c:{chat.id}", "locks", []))
    if locked and (violations(msg) & locked):
        if not await is_admin(chat, user.id, ctx):
            try:
                await msg.delete()
            except Exception:
                pass
            return True
