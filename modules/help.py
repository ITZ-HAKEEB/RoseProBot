"""/help menu and /start. Each module adds its own section with register_help()."""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import SUPPORT_URL, UPDATES_URL
from core import HELP, build_message, callback, command, esc, mention, reply, sbtn, send_log, user_photo

# Order of the buttons in /help; sections that are not listed here are appended at the end.
HELP_ORDER = ["federation", "filters", "locks", "notes", "reports", "user", "welcome", "moderation",
              "biolink", "nsfw", "owner"]
LABELS = {"nsfw": "NSFW", "biolink": "BioLink"}
HELP_HEADER = "<b>Help</b>\n\nAll commands can be used with the following: / !"


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


@callback(r"^help:")
async def help_cb(update, ctx):
    q = update.callback_query
    arg = q.data.split(":", 1)[1]
    await q.answer()
    if arg == "close":
        await q.message.delete()
    elif arg == "back":
        await q.message.edit_text(HELP_HEADER, reply_markup=help_markup())
    elif arg in HELP:
        await q.message.edit_text(help_text(arg), reply_markup=Markup([[sbtn("Back", "primary", callback_data="help:back")]]))


@command("help")
async def cmd_help(update, ctx):
    if update.effective_chat.type != ChatType.PRIVATE:
        kb = Markup([[sbtn("Help", "primary", url=f"https://t.me/{ctx.bot.username}?start=help")]])
        return await reply(update, "Contact me in private for the full command list.", reply_markup=kb)
    await reply(update, HELP_HEADER, reply_markup=help_markup())


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
    text = (f"👋 <b>Hey {mention(user.id, user.first_name)}!</b>\n\n"
            f"✨ I'm <b>{esc(ctx.bot.first_name or 'Lisa')}</b>, a powerful group management bot that keeps your "
            "chats clean, safe and organised, 24/7.\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>🛡 <b>Moderation</b>: ban, mute, kick and warn\n"
            "🔒 <b>Locks &amp; Filters</b>: 24 lock types and keyword filters\n"
            "🔗 <b>BioLink</b>: stops users who have a link in their bio\n"
            "🔞 <b>NSFW</b>: removes adult text, images and stickers\n"
            "👋 <b>Welcome</b>: text or media messages with buttons\n"
            "📝 <b>Notes &amp; Rules</b>: save them once, share them anytime\n"
            "🌐 <b>Federations</b>: ban a user in many groups at once\n"
            "🚨 <b>Reports</b>: members can call the admins with @admin</blockquote>\n\n"
            "➕ <b>Add me to your group as an admin</b> and give me the <i>Delete messages</i> and "
            "<i>Restrict members</i> rights to get started.\n\n"
            "Tap <b>Help</b> below to see every command 👇")
    kb = Markup([
        [sbtn("Add me to a group", "primary", url=f"https://t.me/{ctx.bot.username}?startgroup=true&admin=delete_messages+restrict_members+pin_messages+invite_users")],
        [sbtn("support", "success", url=SUPPORT_URL), sbtn("updates", "success", url=UPDATES_URL)],
        [sbtn("Help", "primary", callback_data="help:back")],
    ])
    await reply(update, text, reply_markup=kb)
