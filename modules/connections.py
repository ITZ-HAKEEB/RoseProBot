"""/connect, /connections, /disconnect: manage a group from a private chat."""
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from core import NOT_CONNECTED, callback, command, esc, is_admin, reply

@command("connect")
async def cmd_connect(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type != ChatType.PRIVATE:
        if not await is_admin(chat, user.id, ctx):
            return await reply(update, "Only admins can connect.")
        _add_conn(user.id, chat.id)
        kb = Markup([[Btn("Open private chat", url=f"https://t.me/{ctx.bot.username}")]])
        return await reply(update, "Connected! Now manage this group from my private chat.", reply_markup=kb)
    if not ctx.args or not re.match(r"^-?\d+$", ctx.args[0]):
        return await reply(update, "Send /connect in your group (as admin), or /connect &lt;chat id&gt; here.")
    cid = int(ctx.args[0])
    try:
        c = await ctx.bot.get_chat(cid)
    except Exception:
        return await reply(update, "I'm not in that chat.")
    if not await is_admin(c, user.id, ctx):
        return await reply(update, "You must be an admin of that chat.")
    _add_conn(user.id, cid)
    await reply(update, f"Connected to <b>{esc(c.title)}</b>. Settings commands now change that group.")


def _add_conn(uid, cid):
    lst = db.get(f"u:{uid}", "conns", [])
    if cid not in lst:
        lst.append(cid)
    db.put(f"u:{uid}", "conns", lst)
    db.put(f"u:{uid}", "conn", cid)


@command("connections")
async def cmd_connections(update, ctx):
    user = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        return await reply(update, "Use this in private chat with me.")
    lst, cur = db.get(f"u:{user.id}", "conns", []), db.get(f"u:{user.id}", "conn")
    if not lst:
        return await reply(update, NOT_CONNECTED)
    rows = []
    for cid in lst:
        try:
            c = await ctx.bot.get_chat(cid)
            rows.append([Btn(("✅ " if cid == cur else "") + (c.title or str(cid)), callback_data=f"conn:{cid}")])
        except Exception:
            pass
    await reply(update, "Pick the group your settings commands should change:", reply_markup=Markup(rows))


@callback(r"^conn:")
async def conn_cb(update, ctx):
    q = update.callback_query
    cid = int(q.data.split(":", 1)[1])
    db.put(f"u:{q.from_user.id}", "conn", cid)
    await q.answer("Connected")
    await q.message.edit_text("Selected. Settings commands now change that group.")


@command("disconnect")
async def cmd_disconnect(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    lst, cur = db.get(f"u:{user.id}", "conns", []), db.get(f"u:{user.id}", "conn")
    if chat.type != ChatType.PRIVATE:
        cid = chat.id
    elif ctx.args and ctx.args[0].lower() == "all":
        db.put(f"u:{user.id}", "conns", [])
        db.delete(f"u:{user.id}", "conn")
        return await reply(update, "Disconnected from all groups.")
    elif ctx.args and re.match(r"^-?\d+$", ctx.args[0]):
        cid = int(ctx.args[0])
    else:
        cid = cur
    if cid not in lst:
        return await reply(update, "You are not connected to that chat.")
    lst.remove(cid)
    db.put(f"u:{user.id}", "conns", lst)
    if cur == cid:
        if lst:
            db.put(f"u:{user.id}", "conn", lst[-1])
        else:
            db.delete(f"u:{user.id}", "conn")
    await reply(update, "Disconnected.")
