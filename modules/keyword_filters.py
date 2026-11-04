"""Keyword filters: /filter, /filters, /stop (auto-replies)."""
import re

import db
from core import args_text, build_message, command, esc, fill_for, plain_text, register_help, reply, split_quoted, target, watcher

register_help('filters', [
    ('filter', 'Add a keyword filter: /filter &lt;word&gt; &lt;reply&gt; (or reply to a message)'),
    ('filters', 'List the keyword filters of this chat'),
    ('stop', 'Remove a filter: /stop &lt;word&gt;'),
])


@command("filter")
async def cmd_filter(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    msg = update.effective_message
    kw, resp = split_quoted(args_text(msg))
    if msg.reply_to_message and not resp:
        resp = msg.reply_to_message.text or msg.reply_to_message.caption or ""
    if not kw or not resp:
        return await reply(update, 'Usage: /filter &lt;word&gt; &lt;reply&gt;  (or  /filter "two words" reply, or reply to a message)')
    db.put(f"f:{chat.id}", kw.lower(), resp)
    await reply(update, f"Filter <code>{esc(kw)}</code> saved.")


@command("stop")
async def cmd_stop(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    kw, _ = split_quoted(args_text(update.effective_message))
    if kw and db.delete(f"f:{chat.id}", kw.lower()):
        return await reply(update, f"Filter <code>{esc(kw)}</code> removed.")
    await reply(update, "No such filter.")


@command("filters")
async def cmd_filters(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    f = db.items(f"f:{chat.id}")
    if not f:
        return await reply(update, "No filters in this chat.")
    await reply(update, f"<b>Filters in {esc(chat.title)}</b>\n\n" + "\n".join(f"• <code>{esc(k)}</code>" for k in sorted(f)))


@watcher(80)
async def filter_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    text = plain_text(msg)
    if not text:
        return
    low = text.lower()
    for kw, resp in db.items(f"f:{chat.id}").items():
        if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", low):
            txt, kb = build_message(resp, fill_for(user, chat))
            await msg.reply_text(txt, reply_markup=kb)
            return True
