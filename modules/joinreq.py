"""When someone requests to join a group/channel where the bot is admin, the bot messages them in private
(Telegram allows this even if the user never pressed /start)."""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import Forbidden

import db
from config import JOIN_PHOTO, SUPPORT_URL, UPDATES_URL
from core import esc, log, mention, sbtn, send_log, user_photo

bot_photo_cache = {}


def build_text(user, chat, bot):
    # bot = telegram Bot (has first_name once initialised)
    return (
        f"HEY ~ <b>{mention(user.id, user.first_name)}</b> 👋\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"THANKS FOR REQUESTING TO JOIN <b>{esc(chat.title)}</b>!\n\n"
        f"🤖 I AM <b>{esc(bot.first_name or "Bot")}</b> — A GROUP MANAGEMENT BOT\n\n"
        "<blockquote>🚫 Deletes messages with 18+ and abusive words\n"
        "🛡 Restricts users who send banwords\n"
        "👮 Admins are always excluded\n"
        "⚡ 100% automatic, runs 24/7</blockquote>\n\n"
        "SEND /start TO SEE MY MENU &amp; COMMANDS 📋"
    )


async def _try_dm(bot, chat_id, text, kb, photo):
    """One DM attempt (photo first, plain text as fallback). Returns (sent, error_text, forbidden)."""
    err, forbidden = None, False
    if photo:
        try:
            await bot.send_photo(chat_id, photo, caption=text, reply_markup=kb)
            return True, None, False
        except Forbidden as e:
            return False, f"Forbidden: {e}", True      # text would fail the same way, don't waste a call
        except Exception as e:
            err = f"photo: {type(e).__name__}: {e}"
            log.warning("join-request photo failed: %s", e)
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        return True, None, False
    except Forbidden as e:
        return False, f"Forbidden: {e}", True
    except Exception as e:
        return False, err or f"{type(e).__name__}: {e}", False


async def on_join_request(update, ctx):
    req = update.chat_join_request
    user, chat = req.from_user, req.chat
    log.info("Join request: user %s -> chat %s (%s)", user.id, chat.id, chat.title)
    if user.is_bot:
        return
    bot = ctx.bot
    kb = Markup([
        [sbtn("Add me to a group", "primary", url=f"https://t.me/{bot.username}?startgroup=true&admin=delete_messages+restrict_members+pin_messages+invite_users")],
        [sbtn("Support", "success", url=SUPPORT_URL), sbtn("Updates", "success", url=UPDATES_URL)],
    ])
    text = build_text(user, chat, bot)

    # 1) DM FIRST. Telegram only lets the bot message the requester through `user_chat_id`, and only for
    #    ~5 minutes while the request is still pending, so nothing slow (db, photo lookups) goes before it.
    photo = JOIN_PHOTO or bot_photo_cache.get("id")
    if not photo and not JOIN_PHOTO:
        photo = await user_photo(bot, bot.id)
        bot_photo_cache["id"] = photo
    dm_id = getattr(req, "user_chat_id", None) or user.id
    sent, err, forbidden = await _try_dm(bot, dm_id, text, kb, photo)

    # 2) Request window closed (already approved/declined by an admin or another bot, or older than 5 min).
    #    If the user ever started this bot, a normal DM to their id still works.
    if not sent and forbidden and dm_id != user.id:
        sent, err2, _ = await _try_dm(bot, user.id, text, kb, photo)
        if sent:
            err = None
        else:
            err = (err or "") + " (request already handled/expired and user never started the bot)"

    # 3) Bookkeeping after the DM.
    try:
        db.put("bc_users", user.id, user.full_name)
    except Exception:
        log.exception("join-request: db write failed")
    await send_log(bot, f"📩 <b>Join request</b>\nUser: {mention(user.id, user.first_name)} (<code>{user.id}</code>)\n"
                        f"Chat: {esc(chat.title)} (<code>{chat.id}</code>)\nDM: {'sent ✅' if sent else 'failed ❌'}"
                        + (f"\nError: <code>{esc(err)}</code>" if err else ""),
                   photo=await user_photo(bot, user.id))
