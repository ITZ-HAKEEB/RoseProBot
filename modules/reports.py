"""/report and @admin."""
import re

from telegram.constants import ChatType

from core import command, is_admin, mention, plain_text, register_help, reply, watcher

register_help('reports', [
    ('report', 'Report the replied message to the admins (also: @admin)'),
])


async def do_report(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type == ChatType.PRIVATE:
        return await reply(update, "Use this in a group.")
    if not msg.reply_to_message:
        return await reply(update, "Reply to the message you want to report.")
    rep = msg.reply_to_message.from_user
    if rep and await is_admin(chat, rep.id, ctx):
        return await reply(update, "You can't report an admin.")
    adms = await ctx.bot.get_chat_administrators(chat.id)
    hidden = "".join(f'<a href="tg://user?id={a.user.id}">\u200b</a>' for a in adms if not a.user.is_bot)
    who = mention(rep.id, rep.first_name) if rep else "the user"
    await msg.reply_to_message.reply_text(f"⚠️ {mention(user.id, user.first_name)} reported {who} to the admins.{hidden}")


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
