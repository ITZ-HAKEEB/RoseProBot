"""When someone requests to join a group/channel where the bot is admin, the bot messages them in private
(Telegram allows this even if the user never pressed /start)."""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

import db
from config import JOIN_PHOTO, SUPPORT_URL, UPDATES_URL
from core import esc, log, mention, send_log, user_photo


def build_text(user, chat, bot):
    return (
        f"HEY ~ <b>{mention(user.id, user.first_name)}</b> 👋\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"THANKS FOR REQUESTING TO JOIN <b>{esc(chat.title)}</b>!\n\n"
        f"🤖 I AM <b>{esc(bot.first_name)}</b> — A GROUP MANAGEMENT BOT\n\n"
        "<blockquote>🚫 Deletes messages with 18+ and abusive words\n"
        "🛡 Restricts users who send banwords\n"
        "👮 Admins are always excluded\n"
        "⚡ 100% automatic, runs 24/7</blockquote>\n\n"
        "SEND /start TO SEE MY MENU &amp; COMMANDS 📋"
    )


async def on_join_request(update, ctx):
    req = update.chat_join_request
    user, chat = req.from_user, req.chat
    if user.is_bot:
        return
    db.put("bc_users", user.id, user.full_name)       # now a known user -> broadcast can reach them
    kb = Markup([
        [Btn("Add me to a group", url=f"https://t.me/{ctx.bot.username}?startgroup=true&admin=delete_messages+restrict_members+pin_messages+invite_users")],
        [Btn("Support", url=SUPPORT_URL), Btn("Updates", url=UPDATES_URL)],
    ])
    text = build_text(user, chat, ctx.bot.bot)
    sent = False
    try:
        photo = JOIN_PHOTO or await user_photo(ctx.bot, ctx.bot.id)      # env photo, else the bot's own picture
        if photo:
            try:
                await ctx.bot.send_photo(req.user_chat_id, photo, caption=text, reply_markup=kb)
                sent = True
            except Exception as e:
                log.warning("join-request photo failed: %s", e)
        if not sent:
            await ctx.bot.send_message(req.user_chat_id, text, reply_markup=kb)
            sent = True
    except Exception as e:
        log.warning("join-request DM to %s failed: %s", user.id, e)
    await send_log(ctx.bot, f"📩 <b>Join request</b>\nUser: {mention(user.id, user.first_name)} (<code>{user.id}</code>)\n"
                            f"Chat: {esc(chat.title)} (<code>{chat.id}</code>)\nDM: {'sent ✅' if sent else 'failed ❌'}",
                   photo=await user_photo(ctx.bot, user.id))
