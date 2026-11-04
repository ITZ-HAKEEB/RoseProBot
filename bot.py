"""Entry point. Features live in modules/, shared plumbing in core.py, settings in config.py."""
import logging
import platform
import re

import telegram

from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, Defaults, MessageHandler, filters

import config
import core
import db
import modules  # noqa: F401  (registers every command / watcher / help section)
from core import fmt_time, now
from core import COMMANDS, esc, is_admin, log, reply, send_log, track_chat, mention

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

CMD_RE = re.compile(r"^([/!])(\w+)(?:@(\w+))?(?:\s|$)")


async def log_new_chat(ctx, chat, user, ev_from=None):
    ev_from = ev_from or user
    if chat.type == ChatType.PRIVATE:
        await send_log(ctx.bot, f"👤 <b>New user</b>\n{mention(user.id, user.first_name)}\nID: <code>{user.id}</code>")
    else:
        by = ev_from
        await send_log(ctx.bot, f"➕ <b>New group</b>\n{esc(chat.title)}\nID: <code>{chat.id}</code>\nAdded by: {mention(by.id, by.first_name)} (<code>{by.id}</code>)")


async def on_my_chat_member(update, ctx):
    """Bot added to / removed from a chat, or a user blocked / unblocked the bot."""
    ev, chat = update.my_chat_member, update.effective_chat
    old, new = ev.old_chat_member.status, ev.new_chat_member.status
    scope = "bc_users" if chat.type == ChatType.PRIVATE else "bc_chats"
    if new in ("left", "kicked"):
        db.delete(scope, chat.id)
        core._SEEN.discard(chat.id)
        if chat.type != ChatType.PRIVATE:
            await send_log(ctx.bot, f"➖ <b>Removed from group</b>\n{esc(chat.title)}\nID: <code>{chat.id}</code>\nBy: {mention(ev.from_user.id, ev.from_user.first_name)}")
    elif old in ("left", "kicked") and new in ("member", "administrator"):
        track_chat(chat)
        if chat.type != ChatType.PRIVATE:      # private /start is logged by cmd_start, every time
            await log_new_chat(ctx, chat, ev.from_user)


async def post_init(app):
    """Runs exactly once per process start: one detailed message in the log chat."""
    me = await app.bot.get_me()
    log.info("Logged in as @%s", me.username)
    n = (db.get("meta", "starts", 0) or 0) + 1
    db.put("meta", "starts", n)
    users, groups = len(db.scope_keys("bc_users")), len(db.scope_keys("bc_chats"))
    db_kind = "PostgreSQL" if db.engine.dialect.name.startswith("postgres") else "SQLite"
    await send_log(app.bot,
        "✅ <b>BOT STARTED</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Bot:</b> {esc(me.full_name)} (@{esc(me.username)})\n"
        f"🆔 <b>Bot ID:</b> <code>{me.id}</code>\n"
        f"🔢 <b>Start count:</b> #{n}\n"
        f"🕒 <b>Time:</b> {fmt_time(now())}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ <b>Commands:</b> {len(COMMANDS)}\n"
        f"👀 <b>Watchers:</b> {len(core.WATCHERS)}\n"
        f"👤 <b>Users:</b> {users}\n"
        f"👥 <b>Groups:</b> {groups}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🗄 <b>Database:</b> {db_kind}\n"
        f"🐍 <b>Python:</b> {platform.python_version()}\n"
        f"📦 <b>PTB:</b> {telegram.__version__}\n"
        f"💻 <b>Host:</b> {esc(platform.system())} {esc(platform.machine())}\n"
        "🟢 <b>Status:</b> Online and ready")


async def dispatcher(update, ctx):
    msg = update.effective_message
    m = CMD_RE.match(msg.text or "")
    if not m:
        return
    name, tag = m.group(2).lower(), m.group(3)
    if tag and tag.lower() != (ctx.bot.username or "").lower():
        return
    fn = COMMANDS.get(name)
    if not fn:
        return
    chat, user = update.effective_chat, update.effective_user
    track_chat(chat)
    if chat.type != ChatType.PRIVATE and name in db.get(f"c:{chat.id}", "disabled", []):
        if not await is_admin(chat, user.id, ctx):
            return
    ctx.args = (msg.text or "").split()[1:]
    try:
        await fn(update, ctx)
    except Exception as e:
        log.exception("command %s failed", name)
        try:
            await reply(update, f"⚠️ Something went wrong: <code>{esc(type(e).__name__)}</code>. Make sure I'm admin with the needed rights.")
        except Exception:
            pass


async def watcher(update, ctx):
    """Runs every registered watcher (modules/*.py, lowest priority first) until one returns True."""
    msg, user = update.effective_message, update.effective_user
    if not msg or not user or user.is_bot:
        return
    track_chat(update.effective_chat)      # groups are logged only when the bot is added (on_my_chat_member)
    for _, fn in core.WATCHERS:
        try:
            if await fn(update, ctx):
                return
        except Exception:
            log.exception("watcher %s failed", fn.__name__)


async def on_join(update, ctx):
    msg, chat = update.effective_message, update.effective_chat
    adder_admin = await is_admin(chat, msg.from_user.id, ctx) if msg.from_user else True
    for u in msg.new_chat_members:
        for _, hook in core.JOIN_HOOKS:
            try:
                if await hook(update, ctx, u, adder_admin):
                    break
            except Exception:
                log.exception("join hook %s failed", hook.__name__)


async def on_left(update, ctx):
    u = update.effective_message.left_chat_member
    for hook in core.LEFT_HOOKS:
        try:
            await hook(update, ctx, u)
        except Exception:
            log.exception("left hook %s failed", hook.__name__)


async def on_error(update, ctx):
    log.error("Unhandled error", exc_info=ctx.error)


def main():
    app = (Application.builder().token(config.TOKEN)
           .defaults(Defaults(parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True)))
           .post_init(post_init).build())
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.UpdateType.EDITED_MESSAGE, dispatcher), group=0)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_join), group=0)
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left), group=0)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL & ~filters.UpdateType.EDITED_MESSAGE,
                                   watcher), group=1)
    for pattern, fn in core.CALLBACKS:
        app.add_handler(CallbackQueryHandler(fn, pattern=pattern))
    app.add_error_handler(on_error)
    log.info("Bot starting… %d commands, %d watchers", len(COMMANDS), len(core.WATCHERS))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
