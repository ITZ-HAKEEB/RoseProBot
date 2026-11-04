"""Welcome / goodbye messages: text or media (photo, video, GIF, sticker, voice, document), formatting,
placeholders and coloured inline buttons. /markdownhelp shows the full guide."""
import html
import re

from telegram.error import BadRequest

import db
from core import (COMMANDS, command, esc, fill_for, is_admin, join_hook, left_hook, log, md_from_entities, parse_buttons,
                  build_message, register_help, reply, target)

register_help("welcome", [
    ("markdownhelp", "How to format welcome/goodbye messages: markdown, placeholders, buttons, button colours"),
    ("welcome", "Live preview of the welcome message. /welcome on|off to enable or disable it"),
    ("setwelcome", "Set the welcome: text, or reply to a photo / video / GIF / sticker / voice / document (add text after the command, or use its caption)"),
    ("resetwelcome", "Restore the default welcome message"),
    ("goodbye", "Live preview of the goodbye message. /goodbye on|off to enable or disable it"),
    ("setgoodbye", "Set the goodbye message (same options as /setwelcome)"),
    ("resetgoodbye", "Restore the default goodbye message"),
])

DEFAULT_WELCOME = "Hey {first}, welcome to {chatname}!"
DEFAULT_GOODBYE = "Goodbye {first}!"
MAX_TEXT, MAX_CAPTION = 1000, 1024

MD_HELP = (
    "<b>Custom welcome / goodbye messages</b>\n\n"
    "<b>Set it</b>\n"
    "/setwelcome your text — or reply to a photo, video, GIF, sticker, voice or document with /setwelcome "
    "(add text after the command, or use the media's own caption). Same for /setgoodbye.\n"
    "/welcome shows a live preview · /welcome off disables · /resetwelcome restores the default.\n\n"
    "<b>Formatting</b>\n"
    "<code>*bold*</code> <code>_italic_</code> <code>__underline__</code> <code>~strike~</code> "
    "<code>||spoiler||</code> <code>`code`</code> <code>[text](https://example.com)</code>\n\n"
    "<b>Placeholders</b>\n"
    "<code>{first} {last} {fullname} {mention} {username} {id} {chatname}</code>\n\n"
    "<b>Inline buttons</b> (own line each)\n"
    "<code>[Rules](buttonurl://https://example.com/rules)</code>\n"
    "Tip: a line that contains only <code>[Text](https://link)</code> also becomes a button.\n"
    "Add <code>:same</code> at the end of the link to put it on the same row as the previous button:\n"
    "<code>[Chat](buttonurl://https://t.me/mychat:same)</code>\n"
    "Max 8 buttons, 4 per row. Links must be http(s):// or tg://.\n\n"
    "<b>Button colours</b>\n"
    "Add a colour after the link: <code>:primary</code> (blue), <code>:success</code> (green), "
    "<code>:danger</code> (red). No colour (or <code>:default</code>) keeps the normal look. "
    "Combine with <code>:same</code> in any order:\n"
    "<code>[Join](buttonurl://https://t.me/mychat:success)</code>\n"
    "<code>[Rules](buttonurl://https://example.com/rules:danger:same)</code>\n\n"
    "<b>Example</b>\n"
    "<pre>/setwelcome Welcome {mention} to *{chatname}*!\n"
    "Please read the _rules_.\n"
    "[Rules](buttonurl://https://example.com/rules)\n"
    "[Channel](buttonurl://https://t.me/mychannel:success)\n"
    "[Support](buttonurl://https://t.me/mysupport:danger:same)</pre>\n\n"
    "<b>Limits</b>\n"
    "Text up to 1000 characters; with media the caption can be up to 1024. Stickers cannot have captions: "
    "the text is sent right after the sticker."
)


@command("markdownhelp", "formatting")
async def cmd_mdhelp(update, ctx):
    await reply(update, MD_HELP)


# ───────────────────────── media ─────────────────────────
def extract_media(m):
    """{'type', 'file_id'} for the media of message `m`, or None."""
    if m.photo:
        return {"type": "photo", "file_id": m.photo[-1].file_id}
    if m.animation:                      # before document: GIFs also carry a document
        return {"type": "animation", "file_id": m.animation.file_id}
    if m.video:
        return {"type": "video", "file_id": m.video.file_id}
    if m.sticker:
        return {"type": "sticker", "file_id": m.sticker.file_id}
    if m.voice:
        return {"type": "voice", "file_id": m.voice.file_id}
    if m.document:
        return {"type": "document", "file_id": m.document.file_id}
    return None


def _plain(txt):
    return html.unescape(re.sub(r"<[^>]+>", "", txt))


async def send_greeting(bot, chat_id, cfg, default_text, user, chat, count=None):
    """Send a welcome/goodbye (text or media + caption + buttons) to chat_id."""
    raw = cfg.get("text", default_text if not cfg.get("media") else "")
    media = cfg.get("media")
    has_text = bool(parse_buttons(raw, True)[0])
    txt, kb = build_message(raw, fill_for(user, chat, count), link_lines=True)

    async def deliver(txt, **fmt):
        if not media:
            return await bot.send_message(chat_id, txt, reply_markup=kb, **fmt)
        kind, fid = media["type"], media["file_id"]
        if kind == "sticker":
            await bot.send_sticker(chat_id, fid, reply_markup=None if has_text else kb)
            if has_text:
                await bot.send_message(chat_id, txt, reply_markup=kb, **fmt)
            return
        send = {"photo": bot.send_photo, "video": bot.send_video, "animation": bot.send_animation,
                "voice": bot.send_voice, "document": bot.send_document}[kind]
        return await send(chat_id, fid, caption=txt if has_text else None, reply_markup=kb, **fmt)

    try:
        await deliver(txt)
    except BadRequest as e:              # e.g. badly nested formatting: fall back to plain text
        log.warning("greeting formatting rejected (%s), sending plain text", e)
        await deliver(_plain(txt), parse_mode=None)


# ───────────────────────── commands ─────────────────────────
def _greeting_cmds(kind, default_on, default_text):
    async def show(update, ctx):
        chat = await target(update, ctx, admin=False)
        if not chat:
            return
        cfg = db.get(f"c:{chat.id}", kind, {})
        if ctx.args and ctx.args[0].lower() in ("on", "off", "yes", "no"):
            if not await is_admin(chat, update.effective_user.id, ctx):
                return await reply(update, "Admins only.")
            cfg["on"] = ctx.args[0].lower() in ("on", "yes")
            db.put(f"c:{chat.id}", kind, cfg)
            return await reply(update, f"{kind.title()} message turned {'on' if cfg['on'] else 'off'}.")
        on = cfg.get("on", default_on)
        await reply(update, f"{kind.title()} is <b>{'on' if on else 'off'}</b>. Current message (preview):")
        await send_greeting(ctx.bot, update.effective_chat.id, cfg, default_text, update.effective_user, chat)

    async def setter(update, ctx):
        chat = await target(update, ctx)
        if not chat:
            return
        msg = update.effective_message
        rep = msg.reply_to_message
        full = md_from_entities(msg.text or "", msg.entities)      # Telegram's own hidden links -> [text](url)
        parts = full.split(None, 1)
        txt, media = (parts[1] if len(parts) > 1 else ""), None
        if rep:
            media = extract_media(rep)
            if not txt:                                  # text after the command wins over the caption
                txt = (md_from_entities(rep.caption, rep.caption_entities) if media
                       else md_from_entities(rep.text or rep.caption, rep.entities or rep.caption_entities)) or ""
        txt = txt.strip()
        if not txt and not media:
            return await reply(update, f"Usage: /set{kind} &lt;text&gt;, or reply to a photo / video / GIF / sticker / "
                                       "voice / document. See /markdownhelp")
        clean, rows, err = parse_buttons(txt, True)
        if err:
            return await reply(update, "⚠️ " + esc(err))
        limit = MAX_CAPTION if media and media["type"] != "sticker" else MAX_TEXT
        if len(clean) > limit:
            return await reply(update, f"⚠️ Text is too long: {len(clean)} characters, the limit is {limit}"
                                       f"{' for a caption' if limit == MAX_CAPTION else ' (1024 for a media caption)'}.")
        cfg = db.get(f"c:{chat.id}", kind, {})
        cfg["text"], cfg["media"], cfg["on"] = txt, media, True
        db.put(f"c:{chat.id}", kind, cfg)
        what = f" with {media['type']}" if media else ""
        nbtn = sum(len(r) for r in rows)
        what += f", {nbtn} button{'s' if nbtn != 1 else ''}" if nbtn else ""
        warn = ""
        if not nbtn and re.search(r"buttonurl", clean, re.I):
            warn = ("\n\n⚠️ No button was created. A button must be on its own line, like:\n"
                    "<code>[Rules](buttonurl://https://example.com/rules)</code>\n"
                    "I received this text:\n<code>" + esc(txt[:600]) + "</code>")
        extra = " The text is sent right after the sticker." if media and media["type"] == "sticker" and txt else ""
        await reply(update, f"{kind.title()} message saved{what}.{extra} Check it with /{kind}.{warn}")

    async def resetter(update, ctx):
        chat = await target(update, ctx)
        if chat:
            db.delete(f"c:{chat.id}", kind)
            await reply(update, f"{kind.title()} message reset to default.")

    COMMANDS[kind] = show
    COMMANDS["set" + kind] = setter
    COMMANDS["reset" + kind] = resetter


_greeting_cmds("welcome", True, DEFAULT_WELCOME)
_greeting_cmds("goodbye", False, DEFAULT_GOODBYE)


# ───────────────────────── automatic sending ─────────────────────────
@join_hook(90)
async def welcome_join(update, ctx, u, adder_admin):
    chat = update.effective_chat
    cfg = db.get(f"c:{chat.id}", "welcome", {})
    if u.is_bot or not cfg.get("on", True):
        return
    try:
        count = await ctx.bot.get_chat_member_count(chat.id)
    except Exception:
        count = ""
    await send_greeting(ctx.bot, chat.id, cfg, DEFAULT_WELCOME, u, chat, count)


@left_hook
async def goodbye_left(update, ctx, u):
    chat = update.effective_chat
    cfg = db.get(f"c:{chat.id}", "goodbye", {})
    if not cfg.get("on", False) or u.is_bot:
        return
    await send_greeting(ctx.bot, chat.id, cfg, DEFAULT_GOODBYE, u, chat)
