"""Federations: shared ban lists across several groups."""
import uuid

from telegram.constants import ChatType

import db
from config import SUDO
from core import (args_text, command, esc, is_owner_of_chat, join_hook, mention, now, register_help, reply,
                  resolve_user, watcher)

register_help('federation', [
    ('delfed', 'Delete a federation you own (type its id to confirm)'),
    ('fban', 'Ban a user in every chat of the federation (federation owner / admins)'),
    ('fbanlist', 'List the latest bans of your federation (federation owner / admins)'),
    ('fdemote', 'Remove a federation admin (federation owner only)'),
    ('fedadmins', "List the owner and admins of this chat's federation"),
    ('fedchats', 'List the chats of your federation (federation owner only)'),
    ('fedinfo', "Show a federation (this chat's, or the one with the given id)"),
    ('fpromote', 'Make a user admin of your federation (federation owner only)'),
    ('joinfed', 'Join this chat to a federation: /joinfed &lt;fed id&gt; (chat creator)'),
    ('leavefed', 'Remove this chat from its federation (chat creator)'),
    ('myfeds', 'List the federations you own or administer'),
    ('newfed', 'Create a federation: a shared ban list for several groups'),
    ('renamefed', 'Rename a federation you own'),
    ('unfban', 'Lift a federation ban (federation owner / admins)'),
])


def fed_of_chat(chat_id):
    fid = db.get(f"c:{chat_id}", "fed")
    return (fid, db.get("fed", fid)) if fid and db.get("fed", fid) else (None, None)


def can_fed(f, uid):
    return uid in SUDO or uid == f["owner"] or uid in f["admins"]


@command("newfed")
async def cmd_newfed(update, ctx):
    user = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        return await reply(update, "Create federations in private chat with me.")
    name = args_text(update.effective_message).strip()
    if not name:
        return await reply(update, "Usage: /newfed &lt;name&gt;")
    mine = [1 for f in db.items("fed").values() if f["owner"] == user.id]
    if len(mine) >= 5 and user.id not in SUDO:
        return await reply(update, "You can own at most 5 federations.")
    fid = str(uuid.uuid4())
    db.put("fed", fid, {"name": name, "owner": user.id, "admins": [], "chats": [], "bans": {}})
    await reply(update, f"Federation <b>{esc(name)}</b> created!\nID: <code>{fid}</code>\n"
                        "Join a group with /joinfed &lt;id&gt; (sent in the group by its creator).")


@command("renamefed")
async def cmd_renamefed(update, ctx):
    if len(ctx.args) < 2:
        return await reply(update, "Usage: /renamefed &lt;fed id&gt; &lt;new name&gt;")
    f = db.get("fed", ctx.args[0])
    if not f or f["owner"] != update.effective_user.id:
        return await reply(update, "Federation not found, or you don't own it.")
    f["name"] = " ".join(ctx.args[1:])
    db.put("fed", ctx.args[0], f)
    await reply(update, "Federation renamed.")


@command("delfed")
async def cmd_delfed(update, ctx):
    user = update.effective_user
    if not ctx.args:
        return await reply(update, "Usage: /delfed &lt;fed id&gt;")
    f = db.get("fed", ctx.args[0])
    if not f or (f["owner"] != user.id and user.id not in SUDO):
        return await reply(update, "Federation not found, or you don't own it.")
    if len(ctx.args) > 1 and ctx.args[1] == ctx.args[0]:
        for cid in f["chats"]:
            db.delete(f"c:{cid}", "fed")
        db.delete("fed", ctx.args[0])
        return await reply(update, f"Federation <b>{esc(f['name'])}</b> deleted.")
    await reply(update, f"This deletes <b>{esc(f['name'])}</b> and its ban list.\nTo confirm send:\n"
                        f"<code>/delfed {ctx.args[0]} {ctx.args[0]}</code>")


@command("myfeds")
async def cmd_myfeds(update, ctx):
    uid = update.effective_user.id
    mine = [(k, f) for k, f in db.items("fed").items() if f["owner"] == uid or uid in f["admins"]]
    if not mine:
        return await reply(update, "You don't own or administer any federation. Create one with /newfed.")
    await reply(update, "<b>Your federations</b>\n\n" + "\n\n".join(
        f"<b>{esc(f['name'])}</b> ({'owner' if f['owner'] == uid else 'admin'})\n<code>{k}</code>" for k, f in mine))


@command("joinfed")
async def cmd_joinfed(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == ChatType.PRIVATE:
        return await reply(update, "Send this in the group (only the group creator can).")
    if not await is_owner_of_chat(chat, user.id, ctx):
        return await reply(update, "Only the chat creator can join a federation.")
    if not ctx.args:
        return await reply(update, "Usage: /joinfed &lt;fed id&gt;")
    f = db.get("fed", ctx.args[0])
    if not f:
        return await reply(update, "No federation with that id.")
    if fed_of_chat(chat.id)[0]:
        return await reply(update, "This chat is already in a federation. /leavefed first.")
    f["chats"].append(chat.id)
    db.put("fed", ctx.args[0], f)
    db.put(f"c:{chat.id}", "fed", ctx.args[0])
    await reply(update, f"This chat joined federation <b>{esc(f['name'])}</b>.")


@command("leavefed")
async def cmd_leavefed(update, ctx):
    chat, user = update.effective_chat, update.effective_user
    if chat.type == ChatType.PRIVATE or not await is_owner_of_chat(chat, user.id, ctx):
        return await reply(update, "Only the chat creator can do this, in the group.")
    fid, f = fed_of_chat(chat.id)
    if not f:
        return await reply(update, "This chat isn't in a federation.")
    f["chats"] = [c for c in f["chats"] if c != chat.id]
    db.put("fed", fid, f)
    db.delete(f"c:{chat.id}", "fed")
    await reply(update, "This chat left the federation.")


@command("fedinfo")
async def cmd_fedinfo(update, ctx):
    chat = update.effective_chat
    if ctx.args:
        fid, f = ctx.args[0], db.get("fed", ctx.args[0])
    elif chat.type != ChatType.PRIVATE:
        fid, f = fed_of_chat(chat.id)
    else:
        fid, f = None, None
    if not f:
        return await reply(update, "No federation found. Give an id, or use this in a chat that is in one.")
    await reply(update, f"<b>{esc(f['name'])}</b>\nID: <code>{fid}</code>\nOwner: {mention(f['owner'], f['owner'])}\n"
                        f"Admins: {len(f['admins'])}\nChats: {len(f['chats'])}\nBanned users: {len(f['bans'])}")


@command("fedadmins")
async def cmd_fedadmins(update, ctx):
    fid, f = fed_of_chat(update.effective_chat.id)
    if not f:
        return await reply(update, "This chat isn't in a federation.")
    lines = [f"<b>{esc(f['name'])}</b>", "", "👑 " + mention(f["owner"], f["owner"])]
    lines += ["• " + mention(a, a) for a in f["admins"]]
    await reply(update, "\n".join(lines))


@command("fedchats")
async def cmd_fedchats(update, ctx):
    uid = update.effective_user.id
    if not ctx.args:
        return await reply(update, "Usage: /fedchats &lt;fed id&gt;")
    f = db.get("fed", ctx.args[0])
    if not f or (f["owner"] != uid and uid not in SUDO):
        return await reply(update, "Federation not found, or you don't own it.")
    lines = [f"<b>Chats in {esc(f['name'])}</b>", ""]
    for cid in f["chats"]:
        try:
            lines.append(f"• {esc((await ctx.bot.get_chat(cid)).title)} (<code>{cid}</code>)")
        except Exception:
            lines.append(f"• <code>{cid}</code>")
    await reply(update, "\n".join(lines) if f["chats"] else "No chats yet.")


async def _fed_ctx(update, ctx):
    """Fed for fban-style commands: this chat's, or in private the one given as first arg / the only owned one."""
    chat, uid = update.effective_chat, update.effective_user.id
    if chat.type != ChatType.PRIVATE:
        fid, f = fed_of_chat(chat.id)
        if f:
            return fid, f
    feds = [(k, f) for k, f in db.items("fed").items() if can_fed(f, uid)]
    if len(feds) == 1:
        return feds[0]
    await reply(update, "Use this in a chat that belongs to your federation.")
    return None, None


@command("fpromote")
async def cmd_fpromote(update, ctx):
    fid, f = await _fed_ctx(update, ctx)
    if not f:
        return
    if f["owner"] != update.effective_user.id:
        return await reply(update, "Only the federation owner can do that.")
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        if r[0] not in f["admins"]:
            f["admins"].append(r[0])
        db.put("fed", fid, f)
        await reply(update, f"{mention(r[0], r[1])} is now a federation admin.")


@command("fdemote")
async def cmd_fdemote(update, ctx):
    fid, f = await _fed_ctx(update, ctx)
    if not f:
        return
    if f["owner"] != update.effective_user.id:
        return await reply(update, "Only the federation owner can do that.")
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        f["admins"] = [a for a in f["admins"] if a != r[0]]
        db.put("fed", fid, f)
        await reply(update, f"{mention(r[0], r[1])} is no longer a federation admin.")


@command("fban")
async def cmd_fban(update, ctx):
    fid, f = await _fed_ctx(update, ctx)
    if not f:
        return
    if not can_fed(f, update.effective_user.id):
        return await reply(update, "Only federation owner / admins can fban.")
    r = await resolve_user(update, ctx, ctx.args)
    if not r:
        return
    uid, name, rest = r
    if can_fed(f, uid):
        return await reply(update, "I won't fban a federation admin.")
    f["bans"][str(uid)] = {"reason": " ".join(rest), "t": now(), "name": name}
    db.put("fed", fid, f)
    done = 0
    for cid in f["chats"]:
        try:
            await ctx.bot.ban_chat_member(cid, uid)
            done += 1
        except Exception:
            pass
    await reply(update, f"🚫 <b>FedBan</b> in <b>{esc(f['name'])}</b>\nUser: {mention(uid, name)} (<code>{uid}</code>)\n"
                        f"Reason: {esc(' '.join(rest)) or 'none'}\nBanned in {done}/{len(f['chats'])} chats.")


@command("unfban")
async def cmd_unfban(update, ctx):
    fid, f = await _fed_ctx(update, ctx)
    if not f:
        return
    if not can_fed(f, update.effective_user.id):
        return await reply(update, "Only federation owner / admins can unfban.")
    r = await resolve_user(update, ctx, ctx.args)
    if not r:
        return
    if f["bans"].pop(str(r[0]), None) is None:
        return await reply(update, "That user isn't fbanned.")
    db.put("fed", fid, f)
    for cid in f["chats"]:
        try:
            await ctx.bot.unban_chat_member(cid, r[0], only_if_banned=True)
        except Exception:
            pass
    await reply(update, f"✅ {mention(r[0], r[1])} was unbanned from <b>{esc(f['name'])}</b>.")


@command("fbanlist")
async def cmd_fbanlist(update, ctx):
    fid, f = await _fed_ctx(update, ctx)
    if not f:
        return
    if not can_fed(f, update.effective_user.id):
        return await reply(update, "Only federation owner / admins can see the list.")
    latest = sorted(f["bans"].items(), key=lambda kv: kv[1]["t"], reverse=True)[:30]
    if not latest:
        return await reply(update, "The ban list is empty.")
    await reply(update, f"<b>Latest bans in {esc(f['name'])}</b> ({len(f['bans'])} total)\n\n" + "\n".join(
        f"• <code>{k}</code> {esc(v.get('name'))} — {esc(v.get('reason')) or 'no reason'}" for k, v in latest))


@join_hook(10)
async def fed_join(update, ctx, u, adder_admin):
    chat = update.effective_chat
    fid, f = fed_of_chat(chat.id)
    if f and str(u.id) in f["bans"]:
        try:
            await ctx.bot.ban_chat_member(chat.id, u.id)
            await ctx.bot.send_message(chat.id, f"🚫 {mention(u.id, u.first_name)} is fbanned in <b>{esc(f['name'])}</b>: "
                                                f"{esc(f['bans'][str(u.id)].get('reason')) or 'no reason'}")
        except Exception:
            pass
        return True


@watcher(20)
async def fed_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    fid, f = fed_of_chat(chat.id)
    if f and str(user.id) in f["bans"]:
        try:
            await ctx.bot.ban_chat_member(chat.id, user.id)
            await msg.delete()
        except Exception:
            pass
        return True
