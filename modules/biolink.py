"""Anti bio-link: act on users who have a link / @username in their Telegram bio.

How it works: when a non-admin writes in a group where the filter is on, the bot reads the user's
bio (cached for 10 minutes), and if it contains a link the message is deleted and the chosen action
(delete / warn / mute / ban) is applied. Admins and allow-listed users are never touched.
The bot needs the "delete messages" right (and "restrict members" for mute / ban).
"""
import re
import time

from telegram import ChatPermissions, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import SUPPORT_URL, UPDATES_URL
from core import (callback, command, cooldown_ok, esc, is_admin, log, mention, register_help, reply, resolve_user,
                  target, temp_notice, watcher)

ACTIONS = ("mute", "ban", "delete")

register_help("biolink", [
    ("biolink", "Show or toggle the bio-link filter: /biolink on|off. A user with a link or @username in their bio is warned (3 times by default), then muted"),
    ("biolinkaction", "What happens when the warnings run out: /biolinkaction mute|ban|delete (delete = only remove messages, no warnings)"),
    ("biolinklimit", "Number of warnings before the action: /biolinklimit &lt;1-10&gt; (default 3)"),
    ("biolinkallow", "Exempt a user from the filter (reply or user id / @username)"),
    ("biolinkunallow", "Remove a user's exemption"),
    ("biolinkallowed", "List the exempted users"),
])

BIO_TTL = 600   # seconds a clean bio is cached
LINK_TTL = 10   # a bio WITH a link is re-checked this often, so removing the link works almost at once
_BIO = {}      # user id -> (fetched_at, bio)
_WARNED = set()  # (chat id, user id) with pending bio-link warnings

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.(?:me|dog)/|(?<![\w.@])@[A-Za-z]\w{4,31}"
    r"|\b[a-z0-9-]+\.(?:com|net|org|io|me|co|in|xyz|info|link|site|online|club|top|app|bio|ly|gg|cc|tv|vip|live|shop|store)\b)",
    re.I)


def has_link(bio):
    return bool(LINK_RE.search(EMAIL_RE.sub(" ", bio or "")))


async def get_bio(ctx, uid):
    hit = _BIO.get(uid)
    if hit and time.time() - hit[0] < (LINK_TTL if has_link(hit[1]) else BIO_TTL):
        return hit[1]
    try:
        bio = (await ctx.bot.get_chat(uid)).bio or ""
    except Exception:
        bio = ""
    if len(_BIO) > 5000:
        _BIO.clear()
    _BIO[uid] = (time.time(), bio)
    return bio


def get_cfg(chat_id):
    cfg = {"on": False, "action": "mute", "limit": 3, "allow": [], **db.get(f"c:{chat_id}", "biolink", {})}
    if cfg["action"] not in ACTIONS:   # older versions stored "warn"
        cfg["action"] = "mute"
    return cfg


def save_cfg(chat_id, cfg):
    db.put(f"c:{chat_id}", "biolink", cfg)


@command("biolink", "antibiolink")
async def cmd_biolink(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    cfg = get_cfg(chat.id)
    if ctx.args and ctx.args[0].lower() in ("on", "off", "yes", "no"):
        if not await is_admin(chat, update.effective_user.id, ctx):
            return await reply(update, "Admins only.")
        cfg["on"] = ctx.args[0].lower() in ("on", "yes")
        save_cfg(chat.id, cfg)
        return await reply(update, f"Bio-link filter turned {'on' if cfg['on'] else 'off'}.")
    await reply(update, f"<b>Bio-link filter</b> in {esc(chat.title)}: <b>{'on' if cfg['on'] else 'off'}</b>\n"
                        f"Warnings before action: {cfg['limit']}\nThen: {cfg['action']}\nExempted users: {len(cfg['allow'])}\n\n"
                        "Change with /biolink on|off, /biolinklimit and /biolinkaction mute|ban|delete.")


@command("biolinkaction")
async def cmd_biolinkaction(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or ctx.args[0].lower() not in ACTIONS:
        return await reply(update, "Usage: /biolinkaction " + "|".join(ACTIONS))
    cfg = get_cfg(chat.id)
    cfg["action"] = ctx.args[0].lower()
    save_cfg(chat.id, cfg)
    await reply(update, f"Bio-link action set to {cfg['action']}.")


@command("biolinklimit")
async def cmd_biolinklimit(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or not ctx.args[0].isdigit() or not 1 <= int(ctx.args[0]) <= 10:
        return await reply(update, "Usage: /biolinklimit &lt;1-10&gt;")
    cfg = get_cfg(chat.id)
    cfg["limit"] = int(ctx.args[0])
    save_cfg(chat.id, cfg)
    await reply(update, f"Users get {cfg['limit']} warnings before the action.")


@command("biolinkallow")
async def cmd_biolinkallow(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        cfg = get_cfg(chat.id)
        if r[0] not in cfg["allow"]:
            cfg["allow"].append(r[0])
        save_cfg(chat.id, cfg)
        await reply(update, f"{mention(r[0], r[1])} is exempt from the bio-link filter.")


@command("biolinkunallow")
async def cmd_biolinkunallow(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        cfg = get_cfg(chat.id)
        cfg["allow"] = [u for u in cfg["allow"] if u != r[0]]
        save_cfg(chat.id, cfg)
        await reply(update, f"{mention(r[0], r[1])} is no longer exempt.")


@command("biolinkallowed")
async def cmd_biolinkallowed(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    allow = get_cfg(chat.id)["allow"]
    await reply(update, "<b>Exempt from the bio-link filter</b>\n\n" + "\n".join(f"• {mention(u, u)}" for u in allow)
                if allow else "Nobody is exempt.")


def _buttons(extra=None):
    rows = [[Btn("📢 Updates", url=UPDATES_URL), Btn("💬 Support", url=SUPPORT_URL)]]
    if extra:
        rows.insert(0, [extra])
    return Markup(rows)


FULL = dict(can_send_messages=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True,
            can_invite_users=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
            can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True)


@watcher(40)
async def biolink_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type == ChatType.PRIVATE:
        return
    cfg = db.get(f"c:{chat.id}", "biolink")
    if not cfg or not cfg.get("on") or user.id in cfg.get("allow", []):
        return
    if not has_link(await get_bio(ctx, user.id)):      # cached: cheap after the first message
        if (chat.id, user.id) in _WARNED:                # link was removed: start fresh
            _WARNED.discard((chat.id, user.id))
            db.delete(f"bw:{chat.id}", user.id)
        return
    if await is_admin(chat, user.id, ctx):
        return
    try:
        await msg.delete()
    except Exception:
        pass
    if not cooldown_ok((chat.id, user.id, "biolink"), 10):  # a burst of messages counts as one warning
        return True
    cfg = get_cfg(chat.id)
    who = mention(user.id, user.first_name)
    if cfg["action"] == "delete":
        await temp_notice(ctx, chat.id, f"🔗 {who}, links and @usernames in your bio aren't allowed here. "
                                        "Remove it to chat.", 15, reply_markup=_buttons())
        return True
    n = (db.get(f"bw:{chat.id}", user.id) or 0) + 1
    if n < cfg["limit"]:
        db.put(f"bw:{chat.id}", user.id, n)
        _WARNED.add((chat.id, user.id))
        await temp_notice(ctx, chat.id, f"⚠️ {who}, you have a link / @username in your bio. "
                                        f"<b>Warning {n}/{cfg['limit']}</b>\nRemove it from your bio, otherwise you will be "
                                        f"{'muted' if cfg['action'] == 'mute' else 'banned'}.", 20,
                          reply_markup=_buttons())
        return True
    db.delete(f"bw:{chat.id}", user.id)
    _WARNED.discard((chat.id, user.id))
    try:
        if cfg["action"] == "ban":
            await ctx.bot.ban_chat_member(chat.id, user.id)
            await ctx.bot.send_message(chat.id, f"🚫 {who} reached {n}/{cfg['limit']} warnings (link in bio) and was banned.",
                                       reply_markup=_buttons())
        else:
            await ctx.bot.restrict_chat_member(chat.id, user.id, ChatPermissions(can_send_messages=False))
            await ctx.bot.send_message(
                chat.id, f"🔇 {who} reached {n}/{cfg['limit']} warnings (link in bio) and was muted.\n"
                         "Remove the link from your bio and tap the button to get unmuted.",
                reply_markup=_buttons(Btn("✅ I removed it", callback_data=f"bio:{chat.id}:{user.id}")))
    except Exception:
        log.exception("biolink action failed in %s", chat.id)
        await temp_notice(ctx, chat.id, "⚠️ I need the right to delete messages and restrict / ban members.")
    return True


@callback(r"^bio:")
async def bio_unmute_cb(update, ctx):
    q = update.callback_query
    _, cid, uid = q.data.split(":")
    cid, uid = int(cid), int(uid)
    if q.from_user.id != uid:
        return await q.answer("This button is only for the muted user.", show_alert=True)
    _BIO.pop(uid, None)                                   # force a fresh bio lookup
    if has_link(await get_bio(ctx, uid)):
        return await q.answer("Your bio still has a link or @username. Remove it first, then tap again.", show_alert=True)
    try:
        await ctx.bot.restrict_chat_member(cid, uid, ChatPermissions(**FULL))
    except Exception:
        return await q.answer("I couldn't unmute you. Ask an admin.", show_alert=True)
    db.delete(f"bw:{cid}", uid)
    await q.answer("Unmuted!")
    await q.message.edit_text(f"✅ {mention(uid, q.from_user.first_name)} removed the bio link and was unmuted.",
                              reply_markup=_buttons())
