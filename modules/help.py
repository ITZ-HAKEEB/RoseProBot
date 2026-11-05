"""/help menu and /start. Each module adds its own section with register_help()."""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import START_IMAGE, SUPPORT_URL, UPDATES_URL
from core import (HELP, build_message, callback, command, emo, emo_icon, emoji_ids, esc, log, mention, reply, sbtn,
                  send_log, smallcaps, user_photo)

# Order of the buttons in /help; sections that are not listed here are appended at the end.
HELP_ORDER = ["federation", "filters", "locks", "notes", "reports", "user", "welcome", "moderation",
              "biolink", "nsfw", "owner"]
LABELS = {"nsfw": "NSFW", "biolink": "BioLink"}
HELP_HEADER = f"<b>{smallcaps('help')}</b>\n\nAll commands can be used with the following: / !"


def help_sections():
    names = [s for s in HELP_ORDER if s in HELP] + [s for s in HELP if s not in HELP_ORDER]
    return names


def help_text(section):
    lines = [f"<b>{section}</b>", ""]
    for name, desc in HELP[section]:
        lines.append(f"/{name} — {desc}" if " " not in name else f"{name} — {desc}")
    return "\n".join(lines)


def help_markup():
    names = help_sections()
    rows = [[sbtn(LABELS.get(s, s.title()), "primary", callback_data=f"help:{s}") for s in names[i:i + 2]]
            for i in range(0, len(names), 2)]
    rows.append([sbtn("close", "danger", callback_data="help:close")])
    return Markup(rows)


async def _show(q, ctx, text, kb):
    """Edit the help message. The /start message has a picture, which cannot be turned into text: replace it."""
    if q.message.photo:
        await q.message.delete()
        await ctx.bot.send_message(q.message.chat.id, text, reply_markup=kb)
    else:
        await q.message.edit_text(text, reply_markup=kb)


@callback(r"^help:")
async def help_cb(update, ctx):
    q = update.callback_query
    arg = q.data.split(":", 1)[1]
    await q.answer()
    if arg == "close":
        await q.message.delete()
    elif arg == "back":
        await _show(q, ctx, HELP_HEADER, help_markup())
    elif arg in HELP:
        await _show(q, ctx, help_text(arg), Markup([[sbtn("Back", "primary", callback_data="help:back")]]))


@command("help")
async def cmd_help(update, ctx):
    if update.effective_chat.type != ChatType.PRIVATE:
        kb = Markup([[sbtn("Help", "primary", url=f"https://t.me/{ctx.bot.username}?start=help")]])
        return await reply(update, "Contact me in private for the full command list.", reply_markup=kb)
    await reply(update, HELP_HEADER, reply_markup=help_markup())


def start_content(ctx, user, custom):
    sc = smallcaps
    e = lambda s: emo(s, custom)
    text = (f"<b>{sc('welcome')}, {mention(user.id, user.first_name)}!</b>\n\n"
            f"{e('spark')} <b>{esc(ctx.bot.first_name or 'Lisa')}</b> keeps your groups clean, safe and organised, 24/7, "
            "with moderation, filters, welcome messages and more.\n\n"
            f"<b>{sc('what i can do')}:</b>\n"
            f"<blockquote>{e('moderation')} <b>Moderation</b>: ban, mute, kick, warn\n"
            f"{e('locks')} <b>Locks &amp; Filters</b>: 24 lock types, keyword filters\n"
            f"{e('biolink')} <b>BioLink</b>: blocks users with a link in their bio\n"
            f"{e('nsfw')} <b>NSFW</b>: removes adult text, images and stickers\n"
            f"{e('welcome')} <b>Welcome</b>: text or media with buttons\n"
            f"{e('notes')} <b>Notes &amp; Rules</b>: save once, share anytime\n"
            f"{e('federation')} <b>Federations</b>: ban a user in many groups\n"
            f"{e('reports')} <b>Reports</b>: call the admins with @admin</blockquote>\n\n"
            f"<b>{sc('get started')}:</b> add me to your group as an admin with the <i>Delete messages</i> and "
            "<i>Restrict members</i> rights, then use the buttons below to explore every command.")
    add = f"https://t.me/{ctx.bot.username}?startgroup=true&admin=delete_messages+restrict_members+pin_messages+invite_users"
    ic = lambda s: emo_icon(s, custom)
    kb = Markup([
        [sbtn(sc("add me to your group"), "primary", ic("add"), url=add)],
        [sbtn(sc("support"), "success", ic("support"), url=SUPPORT_URL), sbtn(sc("updates"), "success", ic("updates"), url=UPDATES_URL)],
        [sbtn(sc("help"), "primary", ic("help"), callback_data="help:back")],
    ])
    return text, kb


@command("start")
async def cmd_start(update, ctx):
    user, chat = update.effective_user, update.effective_chat
    if chat.type != ChatType.PRIVATE:
        return await reply(update, "I'm alive! Use /help in private to see what I can do.")
    payload = ctx.args[0] if ctx.args else ""
    # Logger: every /start in private is reported, as many times as the user presses it
    uname = f"@{esc(user.username)}" if user.username else "—"
    await send_log(ctx.bot, f"👤 <b>User started the bot</b>\n"
                            f"Name: {mention(user.id, user.full_name)}\n"
                            f"Username: {uname}\n"
                            f"ID: <code>{user.id}</code>" + (f"\nPayload: <code>{esc(payload)}</code>" if payload else ""),
                   photo=await user_photo(ctx.bot, user.id))
    if payload == "help":
        return await reply(update, HELP_HEADER, reply_markup=help_markup())
    if payload.startswith("rules_"):
        cid = payload[6:]
        rules = db.get(f"c:{cid}", "rules")
        if not rules:
            return await reply(update, "This chat has no rules set yet.")
        txt, kb = build_message(rules)
        return await reply(update, "<b>Rules</b>\n\n" + txt, reply_markup=kb)
    custom = bool(emoji_ids())                           # premium emojis are set: try them first
    text, kb = start_content(ctx, user, custom)
    img = START_IMAGE
    if not img:                                           # the bot's own profile picture, looked up once
        if "start_photo" not in ctx.bot_data:
            ctx.bot_data["start_photo"] = await user_photo(ctx.bot, ctx.bot.id) or ""
        img = ctx.bot_data["start_photo"]
    for use_custom in ((True, False) if custom else (False,)):    # premium emojis first, then plain emojis
        text, kb = start_content(ctx, user, use_custom)
        for pic in ((img, "") if img else ("",)):                  # then the picture, then plain text
            try:
                if pic:
                    return await update.effective_message.reply_photo(pic, caption=text, reply_markup=kb)
                return await reply(update, text, reply_markup=kb)
            except Exception:
                log.warning("start message failed (premium emojis: %s, picture: %s)", use_custom, bool(pic), exc_info=True)
                if pic and not use_custom:
                    ctx.bot_data["start_photo"] = ""               # do not try this picture again
