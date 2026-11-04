"""Notes: /save, /get, /notes, /clear and #name."""
import re

import db
from core import args_text, build_message, command, fill_for, plain_text, register_help, reply, split_quoted, target, watcher, esc

register_help('notes', [
    ('clear', 'Delete a note: /clear &lt;name&gt;'),
    ('get', 'Show a saved note (or use #name)'),
    ('notes', 'List the notes saved in this chat'),
    ('save', 'Save a note: /save &lt;name&gt; &lt;text&gt; (or reply to a message)'),
])


async def send_note(update, name, raw):
    txt, kb = build_message(raw, fill_for(update.effective_user, update.effective_chat))
    await update.effective_message.reply_text(txt, reply_markup=kb)


@command("save")
async def cmd_save(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    msg = update.effective_message
    name, body = split_quoted(args_text(msg))
    if msg.reply_to_message and not body:
        body = msg.reply_to_message.text or msg.reply_to_message.caption or ""
    if not name or not body:
        return await reply(update, "Usage: /save &lt;name&gt; &lt;text&gt;  (or reply to a message)")
    db.put(f"n:{chat.id}", name.lower().lstrip("#"), body)
    await reply(update, f"Saved note <code>{esc(name)}</code>. Get it with /get {esc(name)} or #{esc(name)}")


@command("get")
async def cmd_get(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat or not ctx.args:
        return
    n = ctx.args[0].lower().lstrip("#")
    body = db.get(f"n:{chat.id}", n)
    if body is None:
        return await reply(update, "No such note.")
    await send_note(update, n, body)


@command("notes", "saved")
async def cmd_notes(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    names = sorted(db.items(f"n:{chat.id}"))
    if not names:
        return await reply(update, "No notes saved in this chat.")
    await reply(update, f"<b>Notes in {esc(chat.title)}</b>\n\n" + "\n".join(f"• <code>#{esc(n)}</code>" for n in names))


@command("clear")
async def cmd_clear(update, ctx):
    chat = await target(update, ctx)
    if not chat or not ctx.args:
        return
    if db.delete(f"n:{chat.id}", ctx.args[0].lower().lstrip("#")):
        return await reply(update, "Note deleted.")
    await reply(update, "No such note.")


@watcher(70)
async def note_watcher(update, ctx):
    chat = update.effective_chat
    text = plain_text(update.effective_message)
    m = re.match(r"^#(\w+)", text)
    if m:
        body = db.get(f"n:{chat.id}", m.group(1).lower())
        if body is not None:
            await send_note(update, m.group(1), body)
            return True
