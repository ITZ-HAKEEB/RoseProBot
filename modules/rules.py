"""/rules, /setrules, /clearrules and /disable, /enable, /disabled."""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from core import COMMANDS, args_text, build_message, command, reply, target

@command("rules")
async def cmd_rules(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        c = await target(update, ctx, admin=False)
        if not c:
            return
        chat = c
    rules = db.get(f"c:{chat.id}", "rules")
    if not rules:
        return await reply(update, "No rules have been set for this chat yet.")
    if update.effective_chat.type == ChatType.PRIVATE:
        txt, kb = build_message(rules)
        return await reply(update, "<b>Rules</b>\n\n" + txt, reply_markup=kb)
    kb = Markup([[Btn("Rules", url=f"https://t.me/{ctx.bot.username}?start=rules_{chat.id}")]])
    await reply(update, "Tap the button to read the chat rules.", reply_markup=kb)


@command("setrules")
async def cmd_setrules(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    msg = update.effective_message
    txt = args_text(msg) or (msg.reply_to_message.text if msg.reply_to_message else "")
    if not txt:
        return await reply(update, "Give me the rules text, or reply to a message.")
    db.put(f"c:{chat.id}", "rules", txt)
    await reply(update, "Rules saved.")


@command("clearrules")
async def cmd_clearrules(update, ctx):
    chat = await target(update, ctx)
    if chat:
        db.delete(f"c:{chat.id}", "rules")
        await reply(update, "Rules cleared.")


@command("disable")
async def cmd_disable(update, ctx):
    chat = await target(update, ctx)
    if not chat or not ctx.args:
        return
    name = ctx.args[0].lstrip("/!").lower()
    if name in ("disable", "enable", "start"):
        return await reply(update, "That command can't be disabled.")
    if name not in COMMANDS:
        return await reply(update, "Unknown command.")
    lst = db.get(f"c:{chat.id}", "disabled", [])
    if name not in lst:
        lst.append(name)
    db.put(f"c:{chat.id}", "disabled", lst)
    await reply(update, f"/{name} is now disabled for non-admins.")


@command("enable")
async def cmd_enable(update, ctx):
    chat = await target(update, ctx)
    if not chat or not ctx.args:
        return
    name = ctx.args[0].lstrip("/!").lower()
    lst = db.get(f"c:{chat.id}", "disabled", [])
    if name in lst:
        lst.remove(name)
        db.put(f"c:{chat.id}", "disabled", lst)
        return await reply(update, f"/{name} enabled.")
    await reply(update, "That command isn't disabled.")


@command("disabled")
async def cmd_disabled(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    lst = db.get(f"c:{chat.id}", "disabled", [])
    await reply(update, "Disabled commands:\n" + "\n".join("/" + x for x in lst) if lst else "No commands are disabled.")
