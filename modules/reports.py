"""/report and @admin: tag every admin of the group, and also DM them (best effort)."""
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

from core import command, cooldown_ok, esc, is_admin, log, mention, plain_text, register_help, reply, watcher

register_help('reports', [
    ('report', 'Report the replied message to the admins (also: @admin). Admins get tagged and a DM'),
])

TAGS_PER_MESSAGE = 5      # Telegram does not reliably notify when one message mentions many people


def message_link(chat, message_id):
    if chat.username:
        return f"https://t.me/{chat.username}/{message_id}"
    cid = str(chat.id)
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


def tag(user):
    """A visible, clickable dot: Telegram always notifies for it (zero-width mentions are dropped by some clients)."""
    return f'<a href="tg://user?id={user.id}">•</a>'


async def do_report(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type == ChatType.PRIVATE:
        return await reply(update, "Use this in a group.")
    target_msg = msg.reply_to_message
    if not target_msg:
        return await reply(update, "Reply to the message you want to report.")
    rep = target_msg.from_user
    if rep and rep.id == ctx.bot.id:
        return await reply(update, "I can't report myself 🙂")
    if rep and rep.id == user.id:
        return await reply(update, "You can't report yourself.")
    if rep and await is_admin(chat, rep.id, ctx):
        return await reply(update, "You can't report an admin.")
    if not cooldown_ok((chat.id, user.id, "report"), 15):
        return

    try:
        admins = [a.user for a in await ctx.bot.get_chat_administrators(chat.id) if not a.user.is_bot]
    except Exception:
        log.exception("report: could not list admins of %s", chat.id)
        return await reply(update, "⚠️ I couldn't get the admin list of this group.")
    if not admins:
        return await reply(update, "There is no admin to report to.")

    who = mention(rep.id, rep.first_name) if rep else "the sender"
    link = message_link(chat, target_msg.message_id)
    kb = Markup([[Btn("View message", url=link)]]) if link else None
    head = f"⚠️ {mention(user.id, user.first_name)} reported {who} to the admins."

    # 1) tag the admins in the group, a few per message
    chunks = [admins[i:i + TAGS_PER_MESSAGE] for i in range(0, len(admins), TAGS_PER_MESSAGE)]
    first = True
    for chunk in chunks:
        text = (head if first else "👮 Admins:") + "\n" + " ".join(tag(a) for a in chunk)
        try:
            await target_msg.reply_text(text, reply_markup=kb if first else None)
        except Exception:                      # the reported message was deleted: answer the /report message instead
            await msg.reply_text(text, reply_markup=kb if first else None)
        first = False

    # 2) DM every admin who has started the bot (Telegram does not allow DMs to others)
    dm = (f"⚠️ <b>Report in {esc(chat.title)}</b>\n"
          f"By: {mention(user.id, user.first_name)}\nAgainst: {who}\n"
          + (f"\n<i>{esc((target_msg.text or target_msg.caption or '')[:300])}</i>" if (target_msg.text or target_msg.caption) else ""))
    for a in admins:
        if a.id == user.id:
            continue
        try:
            await ctx.bot.send_message(a.id, dm, reply_markup=kb)
        except Exception:
            pass


@command("report")
async def cmd_report(update, ctx):
    await do_report(update, ctx)


@watcher(60)
async def report_watcher(update, ctx):
    msg = update.effective_message
    text = plain_text(msg)
    if text and re.search(r"(^|\s)@admins?(\s|$)", text, re.I) and msg.reply_to_message:
        await do_report(update, ctx)
        return True
