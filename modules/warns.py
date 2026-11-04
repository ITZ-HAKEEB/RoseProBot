"""Warnings: /warn, /warns, /resetwarns, /setwarnlimit, /setwarnaction, /setwarnexpiry, /warnsettings."""
from telegram import ChatPermissions
from telegram.constants import ChatType

import db
from core import command, esc, fmt_time, is_admin, mention, now, reply, resolve_user, target
from modules.moderation import _mod_prepare

def warn_cfg(chat_id):
    c = db.get(f"c:{chat_id}", "warn", {})
    return {"limit": c.get("limit", 3), "action": c.get("action", "ban"), "expiry": c.get("expiry", 0)}


def active_warns(chat_id, uid):
    cfg = warn_cfg(chat_id)
    w = db.get(f"w:{chat_id}", uid, [])
    if cfg["expiry"]:
        w = [x for x in w if now() - x["t"] < cfg["expiry"] * 3600]
    return w


async def do_warn(ctx, chat, uid, name, reason):
    cfg = warn_cfg(chat.id)
    w = active_warns(chat.id, uid) + [{"t": now(), "r": reason}]
    if len(w) >= cfg["limit"]:
        db.delete(f"w:{chat.id}", uid)
        act = cfg["action"]
        if act == "ban":
            await ctx.bot.ban_chat_member(chat.id, uid)
        elif act == "kick":
            await ctx.bot.ban_chat_member(chat.id, uid)
            await ctx.bot.unban_chat_member(chat.id, uid)
        elif act == "mute":
            await ctx.bot.restrict_chat_member(chat.id, uid, ChatPermissions(can_send_messages=False))
        return f"{mention(uid, name)} reached {cfg['limit']}/{cfg['limit']} warnings and was {act}{'ned' if act == 'ban' else 'ed' if act != 'mute' else 'd'}."
    db.put(f"w:{chat.id}", uid, w)
    return f"⚠️ {mention(uid, name)} has been warned ({len(w)}/{cfg['limit']})." + (f"\nReason: {esc(reason)}" if reason else "")


@command("warn")
async def cmd_warn(update, ctx):
    r = await _mod_prepare(update, ctx)
    if r:
        reason = " ".join(r[2])
        await reply(update, await do_warn(ctx, update.effective_chat, r[0], r[1], reason))


@command("warns")
async def cmd_warns(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == ChatType.PRIVATE:
        return await reply(update, "This works in groups only.")
    uid, name = user.id, user.first_name
    if (update.effective_message.reply_to_message or ctx.args) and await is_admin(chat, user.id, ctx):
        r = await resolve_user(update, ctx, ctx.args)
        if not r:
            return
        uid, name = r[0], r[1]
    w, cfg = active_warns(chat.id, uid), warn_cfg(chat.id)
    if not w:
        return await reply(update, f"{mention(uid, name)} has no active warnings.")
    lines = [f"{mention(uid, name)} has {len(w)}/{cfg['limit']} warnings:"]
    lines += [f"{i}. {esc(x['r']) or 'no reason'} ({fmt_time(x['t'])})" for i, x in enumerate(w, 1)]
    await reply(update, "\n".join(lines))


@command("resetwarns")
async def cmd_resetwarns(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE or not await is_admin(chat, update.effective_user.id, ctx):
        return await reply(update, "Admins only, in a group.")
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        db.delete(f"w:{chat.id}", r[0])
        await reply(update, f"Warnings of {mention(r[0], r[1])} were cleared.")


def _set_warn(chat, **kw):
    cfg = db.get(f"c:{chat.id}", "warn", {})
    cfg.update(kw)
    db.put(f"c:{chat.id}", "warn", cfg)


@command("setwarnlimit")
async def cmd_swl(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or not ctx.args[0].isdigit() or int(ctx.args[0]) < 1:
        return await reply(update, "Usage: /setwarnlimit &lt;number ≥ 1&gt;")
    _set_warn(chat, limit=int(ctx.args[0]))
    await reply(update, f"Warn limit set to {ctx.args[0]}.")


@command("setwarnaction")
async def cmd_swa(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or ctx.args[0].lower() not in ("ban", "kick", "mute"):
        return await reply(update, "Usage: /setwarnaction ban|kick|mute")
    _set_warn(chat, action=ctx.args[0].lower())
    await reply(update, f"Warn action set to {ctx.args[0].lower()}.")


@command("setwarnexpiry", "setwarntime")
async def cmd_swe(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or not ctx.args[0].isdigit():
        return await reply(update, "Usage: /setwarnexpiry &lt;hours&gt; (0 = never)")
    _set_warn(chat, expiry=int(ctx.args[0]))
    await reply(update, "Warnings never expire." if ctx.args[0] == "0" else f"Warnings now expire after {ctx.args[0]} hours.")


@command("warnsettings")
async def cmd_warnsettings(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    c = warn_cfg(chat.id)
    await reply(update, f"<b>Warn settings</b>\nLimit: {c['limit']}\nAction: {c['action']}\n"
                        f"Expiry: {str(c['expiry']) + ' hours' if c['expiry'] else 'never'}")


# ───────────────────────── shared punishment helper ─────────────────────────
ACTIONS = ("delete", "warn", "mute", "ban")


async def apply_action(ctx, chat, user, action, reason):
    """Punish `user` in `chat` (used by biolink / nsfw).

    action: delete (nothing beyond removing the message) | warn | mute | ban.
    Returns the text to announce, or None for plain delete. Raises if the bot lacks rights.
    """
    uid, name = user.id, user.first_name
    if action == "warn":
        return await do_warn(ctx, chat, uid, name, reason)
    if action == "mute":
        await ctx.bot.restrict_chat_member(chat.id, uid, ChatPermissions(can_send_messages=False))
        return f"🔇 {mention(uid, name)} was muted. Reason: {esc(reason)}"
    if action == "ban":
        await ctx.bot.ban_chat_member(chat.id, uid)
        return f"🚫 {mention(uid, name)} was banned. Reason: {esc(reason)}"
    return None
