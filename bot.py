"""Entry point. Features live in modules/, shared plumbing in core.py, settings in config.py."""
import logging
import re

from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, Defaults, MessageHandler, filters

import config
import core
import db
import modules  # noqa: F401  (registers every command / watcher / help section)
from core import COMMANDS, esc, is_admin, log, reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

CMD_RE = re.compile(r"^([/!])(\w+)(?:@(\w+))?(?:\s|$)")


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
           .build())
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
