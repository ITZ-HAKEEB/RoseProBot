"""Shared look of the bio-link and NSFW protection messages: a detection card, a 'Protect' log card and the
Unmute / Add Me / Whitelist This User buttons (admin only). Imported by biolink.py and nsfw.py."""
from telegram import ChatPermissions, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

import db
from config import FOOTER_TEXT, UPDATES_URL
from core import callback, esc, fmt_time, is_admin, log, mention, now, temp_notice

FULL = dict(can_send_messages=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True,
            can_invite_users=True, can_send_audios=True, can_send_documents=True, can_send_photos=True,
            can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True)

# kind -> (settings scope, counter scope, icon, label)
KINDS = {"bio": ("biolink", "bw", "🪪", "Bio"), "nsfw": ("nsfw", "nw", "🔞", "NSFW")}
TEMP_SECONDS = 60          # every card is deleted again after this many seconds


def _btn(text, style=None, **kw):
    if style:                                           # button colours: Bot API 9.4+, newer Telegram clients
        kw["api_kwargs"] = {"style": style}
    return Btn(text, **kw)


def footer():
    return f'✦ <a href="{esc(UPDATES_URL)}">{esc(FOOTER_TEXT)}</a> ✦'


def buttons(bot, kind, uid, muted=False, unmuted=False, whitelisted=False):
    add = (f"https://t.me/{bot.username}?startgroup=true"
           "&admin=delete_messages+restrict_members+pin_messages+invite_users")
    top = []
    if muted:
        top.append(_btn("🔊 Unmute", "danger", callback_data=f"gu:um:{kind}:{uid}"))
    elif unmuted:
        top.append(_btn("✅ Unmuted", callback_data="gu:noop"))
    top.append(_btn("➕ Add Me", "success", url=add))
    last = (_btn("✅ Whitelisted", callback_data="gu:noop") if whitelisted
            else _btn("✅ Whitelist This User", "primary", callback_data=f"gu:wl:{kind}:{uid}"))
    return Markup([top, [last]])


def bio_card(user, link, n, result):
    return ("<blockquote>🪪 <b>Bio Link Detected!</b>\n"
            "🗑 <b>Message Deleted</b> — Link Found in Bio.\n"
            "🛡 <b>Remove The Bio Link Or Get Whitelisted!</b>\n\n"
            f"👤 <b>User:</b> {mention(user.id, user.first_name)}\n"
            f"🪪 <b>Bio Link:</b> {esc(link)}\n"
            f"💀 <b>Warnings:</b> {n}\n"
            f"{result}\n\n{footer()}</blockquote>")


def nsfw_card(user, what, n, result=""):
    return ("<blockquote>🔞 <b>NSFW Detected!</b>\n"
            "🗑 <b>Message Deleted</b> — Adult Content Found.\n"
            "🛡 <b>Keep The Group Clean Or Get Whitelisted!</b>\n\n"
            f"👤 <b>User:</b> {mention(user.id, user.first_name)}\n"
            f"🔞 <b>Detected:</b> {esc(what)}\n"
            f"💀 <b>Warnings:</b> {n}\n"
            + (f"{result}\n" if result else "") + f"\n{footer()}</blockquote>")


def protect_card(user, kind, match, strike):
    _, _, icon, label = KINDS[kind]
    return ("<blockquote>🛡 <b>Protect</b>\n"
            f"<b>User:</b> {mention(user.id, user.first_name)} (<code>{user.id}</code>)\n"
            f"<b>Type:</b> {icon} {label}\n"
            f"<b>Match:</b> {esc(match)}\n"
            f"<b>Strike:</b> {strike}\n"
            "<b>Status:</b> ✅ Protection Active\n"
            f"<b>Time:</b> {fmt_time(now())}</blockquote>")


async def send_cards(ctx, chat, user, kind, card, protect, muted=False):
    """Detection card (with buttons) followed by the Protect card. Both are deleted after TEMP_SECONDS (1 minute)."""
    kb = buttons(ctx.bot, kind, user.id, muted=muted)
    try:
        await temp_notice(ctx, chat.id, card, TEMP_SECONDS, reply_markup=kb)
        await temp_notice(ctx, chat.id, protect, TEMP_SECONDS)
    except Exception:
        log.exception("could not send the protection card in %s", chat.id)


async def _restore(ctx, chat_id, uid):
    """Give a muted user the group's normal permissions back."""
    try:
        perms = (await ctx.bot.get_chat(chat_id)).permissions
    except Exception:
        perms = None
    await ctx.bot.restrict_chat_member(chat_id, uid, perms or ChatPermissions(**FULL))


@callback(r"^gu:")
async def guard_buttons(update, ctx):
    q = update.callback_query
    parts = q.data.split(":")
    if parts[1] == "noop":
        return await q.answer()
    chat = q.message.chat
    if not await is_admin(chat, q.from_user.id, ctx):
        return await q.answer("Only admins can use this button.", show_alert=True)
    kind, uid = parts[2], int(parts[3])
    if kind not in KINDS:
        return await q.answer()
    scope, counter = KINDS[kind][0], KINDS[kind][1]
    labels = [b.text for row in q.message.reply_markup.inline_keyboard for b in row]
    was_muted, was_whitelisted = "🔊 Unmute" in labels, "✅ Whitelisted" in labels
    if parts[1] == "um":
        try:
            await _restore(ctx, chat.id, uid)
        except Exception:
            return await q.answer("I couldn't unmute. Check my restrict-members right.", show_alert=True)
        await q.answer("Unmuted!")
        kb = buttons(ctx.bot, kind, uid, unmuted=True, whitelisted=was_whitelisted)
    else:                                                # wl = whitelist
        cfg = db.get(f"c:{chat.id}", scope, {})
        allow = cfg.setdefault("allow", [])
        if uid not in allow:
            allow.append(uid)
        db.put(f"c:{chat.id}", scope, cfg)
        db.delete(f"{counter}:{chat.id}", uid)
        if was_muted:
            try:
                await _restore(ctx, chat.id, uid)
            except Exception:
                log.warning("whitelist: could not unmute %s in %s", uid, chat.id)
        await q.answer("Whitelisted!")
        kb = buttons(ctx.bot, kind, uid, unmuted=was_muted or "✅ Unmuted" in labels, whitelisted=True)
    try:
        await q.edit_message_reply_markup(kb)
    except Exception:
        pass
