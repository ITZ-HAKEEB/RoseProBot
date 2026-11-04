"""Moderation: ban, unban, kick, mute, unmute (the 'moderation' help section also covers warns and rules)."""
from telegram import ChatPermissions
from telegram.constants import ChatType

from core import command, is_admin, mention, register_help, reply, resolve_user

register_help('moderation', [
    ('ban / unban', 'Ban or unban a user'),
    ('kick', 'Remove a user (they can rejoin)'),
    ('mute / unmute', 'Mute or unmute a user'),
    ('warn', 'Warn a user (reply or id)'),
    ('resetwarns', "Clear a user's warnings"),
    ('setwarnlimit', 'Set the warn limit'),
    ('setwarnaction', 'ban / kick / mute when the limit is hit'),
    ('setwarnexpiry', 'Warnings expire after N hours (0 = never)'),
    ('setrules / clearrules', 'Set or clear the chat rules'),
    ('disable / enable', 'Disable or enable a command for non-admins'),
])


async def _mod_prepare(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await reply(update, "This works in groups only.")
        return None
    if not await is_admin(chat, update.effective_user.id, ctx):
        await reply(update, "You need to be an admin to do that.")
        return None
    r = await resolve_user(update, ctx, ctx.args)
    if not r:
        return None
    if await is_admin(chat, r[0], ctx):
        await reply(update, "I won't act against an admin.")
        return None
    return r


@command("ban")
async def cmd_ban(update, ctx):
    r = await _mod_prepare(update, ctx)
    if r:
        await ctx.bot.ban_chat_member(update.effective_chat.id, r[0])
        await reply(update, f"Banned {mention(r[0], r[1])}.")


@command("unban")
async def cmd_unban(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE or not await is_admin(chat, update.effective_user.id, ctx):
        return await reply(update, "Admins only, in a group.")
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        await ctx.bot.unban_chat_member(chat.id, r[0], only_if_banned=True)
        await reply(update, f"Unbanned {mention(r[0], r[1])}.")


@command("kick")
async def cmd_kick(update, ctx):
    r = await _mod_prepare(update, ctx)
    if r:
        await ctx.bot.ban_chat_member(update.effective_chat.id, r[0])
        await ctx.bot.unban_chat_member(update.effective_chat.id, r[0])
        await reply(update, f"Kicked {mention(r[0], r[1])}.")


@command("mute")
async def cmd_mute(update, ctx):
    r = await _mod_prepare(update, ctx)
    if r:
        await ctx.bot.restrict_chat_member(update.effective_chat.id, r[0], ChatPermissions(can_send_messages=False))
        await reply(update, f"Muted {mention(r[0], r[1])}.")


@command("unmute")
async def cmd_unmute(update, ctx):
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE or not await is_admin(chat, update.effective_user.id, ctx):
        return await reply(update, "Admins only, in a group.")
    r = await resolve_user(update, ctx, ctx.args)
    if r:
        full = ChatPermissions(can_send_messages=True, can_send_polls=True, can_send_other_messages=True,
                               can_add_web_page_previews=True, can_invite_users=True, can_send_audios=True,
                               can_send_documents=True, can_send_photos=True, can_send_videos=True,
                               can_send_video_notes=True, can_send_voice_notes=True)
        await ctx.bot.restrict_chat_member(chat.id, r[0], full)
        await reply(update, f"Unmuted {mention(r[0], r[1])}.")
