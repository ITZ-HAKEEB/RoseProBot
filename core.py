"""Shared plumbing: command/help/watcher registries and helper functions.

Every feature lives in its own file under modules/ and registers itself here
with the decorators below (command, callback, watcher, join_hook, left_hook,
register_help).  bot.py only wires the registries into python-telegram-bot.
"""
import asyncio
import html
import logging
import re
import time
from datetime import datetime, timezone

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import LOG_CHANNEL, SUDO

log = logging.getLogger("lisa")

# ───────────────────────── registries ─────────────────────────
COMMANDS = {}      # name -> async fn(update, ctx)
CALLBACKS = []     # (regex pattern, async fn(update, ctx))
WATCHERS = []      # (priority, async fn(update, ctx) -> True to stop the chain)
JOIN_HOOKS = []    # (priority, async fn(update, ctx, user, adder_is_admin) -> True to stop)
LEFT_HOOKS = []    # async fn(update, ctx, user)
HELP = {}          # section -> [(command, description)]


def command(*names):
    def deco(fn):
        for n in names:
            COMMANDS[n] = fn
        return fn
    return deco


def callback(pattern):
    def deco(fn):
        CALLBACKS.append((pattern, fn))
        return fn
    return deco


def watcher(priority=50):
    """Runs on every group message, lowest priority number first."""
    def deco(fn):
        WATCHERS.append((priority, fn))
        WATCHERS.sort(key=lambda x: x[0])
        return fn
    return deco


def join_hook(priority=50):
    def deco(fn):
        JOIN_HOOKS.append((priority, fn))
        JOIN_HOOKS.sort(key=lambda x: x[0])
        return fn
    return deco


def left_hook(fn):
    LEFT_HOOKS.append(fn)
    return fn


def register_help(section, entries):
    HELP.setdefault(section, []).extend(entries)


# ───────────────────────── helpers ─────────────────────────
def esc(s):
    return html.escape(str(s or ""))


def mention(uid, name):
    return f'<a href="tg://user?id={uid}">{esc(name)}</a>'


async def reply(update, text, **kw):
    return await update.effective_message.reply_text(text, **kw)


def args_text(msg):
    t = msg.text or msg.caption or ""
    parts = t.split(None, 1)
    return parts[1] if len(parts) > 1 else ""


async def is_admin(chat, uid, ctx):
    if uid in SUDO or chat.type == ChatType.PRIVATE:
        return True
    try:
        m = await ctx.bot.get_chat_member(chat.id, uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def is_owner_of_chat(chat, uid, ctx):
    if uid in SUDO:
        return True
    try:
        m = await ctx.bot.get_chat_member(chat.id, uid)
        return m.status == "creator"
    except Exception:
        return False


NOT_CONNECTED = "You are not connected to a group.\nSend /connect in your group (as admin),\nor /connect &lt;chat id&gt; here."


async def target(update, ctx, admin=True):
    """Chat a settings command applies to: this group, or the connected group in PM."""
    chat, user = update.effective_chat, update.effective_user
    if chat.type != ChatType.PRIVATE:
        if admin and not await is_admin(chat, user.id, ctx):
            await reply(update, "You need to be an admin to do that.")
            return None
        return chat
    cid = db.get(f"u:{user.id}", "conn")
    if not cid:
        await reply(update, NOT_CONNECTED)
        return None
    try:
        c = await ctx.bot.get_chat(cid)
    except Exception:
        await reply(update, "I can't reach the connected group any more. Use /connections to pick another.")
        return None
    if admin and not await is_admin(c, user.id, ctx):
        await reply(update, "You are no longer an admin of the connected group.")
        return None
    return c


async def resolve_user(update, ctx, args):
    """Returns (uid, name, remaining_args) or None."""
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        db.put("usernames", (u.username or str(u.id)).lower(), u.id)
        return u.id, u.first_name, args
    if args:
        a = args[0]
        uid = None
        if a.lstrip("-").isdigit():
            uid = int(a)
        elif a.startswith("@"):
            uid = db.get("usernames", a[1:].lower())
        if uid:
            name = str(uid)
            try:
                name = (await ctx.bot.get_chat(uid)).first_name or name
            except Exception:
                pass
            return uid, name, args[1:]
    await reply(update, "I can't find that user. Reply to their message or give a user id / known @username.")
    return None


# Premium (custom) emoji are stored in the text as  ![😀](emoji:5368324170671202286)
CUSTOM_EMOJI_MD = re.compile(r"!\[([^\]\n]+)\]\(emoji:(\d+)\)")


_SC = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"))


def smallcaps(text):
    """'add me to your group' -> 'Aᴅᴅ Mᴇ Tᴏ Yᴏᴜʀ Gʀᴏᴜᴘ' (capital first letters, small capitals after)."""
    out, start = [], True
    for ch in text:
        if ch.isascii() and ch.isalpha():
            out.append(ch.upper() if start else _SC[ch.lower()])
            start = False
        else:
            out.append(ch)
            start = ch in " -/"
    return "".join(out)


def sbtn(text, style=None, icon=None, **kw):
    """Inline button with an optional colour (primary = blue, success = green, danger = red)
    and an optional custom (premium / animated) emoji shown before the text."""
    extra = {}
    if style:
        extra["style"] = style
    if icon:
        extra["icon_custom_emoji_id"] = str(icon)
    if extra:
        kw["api_kwargs"] = extra
    return Btn(text, **kw)


# ───────────────────────── premium (custom) emojis ─────────────────────────
# slot -> normal emoji that is shown when no premium emoji is set for the slot. The owner sets premium emojis with
# /setemoji (see modules/emojis.py); they are stored in the database.
EMOJI_SLOTS = {
    "spark": "✨", "moderation": "🛡", "locks": "🔒", "biolink": "🔗", "nsfw": "🔞", "welcome": "👋",
    "notes": "📝", "federation": "🌐", "reports": "🚨",
    "add": "➕", "support": "💬", "updates": "📢", "help": "❓",
}


def emoji_ids():
    return db.get("bot", "emoji", {}) or {}


def emo(slot, custom=True):
    """HTML for a slot: the premium emoji (animated for Premium users) or the normal emoji."""
    i = emoji_ids().get(slot) if custom else None
    fb = EMOJI_SLOTS[slot]
    return f'<tg-emoji emoji-id="{i}">{fb}</tg-emoji>' if i else fb


def emo_icon(slot, custom=True):
    """Custom emoji id for a button icon, or None."""
    return emoji_ids().get(slot) if custom else None


def md_to_html(text):
    t = esc(text)
    t = CUSTOM_EMOJI_MD.sub(r'<tg-emoji emoji-id="\2">\1</tg-emoji>', t)
    t = re.sub(r"```(.+?)```", r"<pre>\1</pre>", t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+|tg://[^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"(?<![\w])__(.+?)__(?![\w])", r"<u>\1</u>", t, flags=re.S)       # __underline__
    t = re.sub(r"(?<![\w])\*([^*\n]+)\*(?![\w])", r"<b>\1</b>", t)                # *bold*
    t = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"<i>\1</i>", t)                  # _italic_
    t = re.sub(r"(?<![\w])~([^~\n]+)~(?![\w])", r"<s>\1</s>", t)                  # ~strike~
    t = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", t, flags=re.S)   # ||spoiler||
    return t


# [Label](buttonurl://https://example.com[:same][:primary|:success|:danger|:default])
# Lenient on purpose: case-insensitive, "buttonurl:" with or without //, spaces before the modifiers, t.me/x or @user links.
BTN_RE = re.compile(r"\[([^\]\n]+)\]\(\s*buttonurl:(?://)?\s*([^)\s]+?)((?:\s*:(?:same|primary|success|danger|default))*)\s*\)", re.I)
MAX_BUTTONS, BUTTONS_PER_ROW = 8, 4
BUTTON_STYLES = ("primary", "success", "danger")   # blue / green / red (Bot API 9.4+, newer Telegram clients)
BTN_FORMAT_HELP = "Use: [Text](buttonurl://https://example.com) — one button per line, no spaces inside the ( )."


LINK_LINE_RE = re.compile(r"^\s*(?:\[[^\]\n]+\]\(\s*(?:https?|tg)://[^)\s]+\s*\)\s*)+$", re.I)
LINK_RE_1 = re.compile(r"\[([^\]\n]+)\]\(\s*((?:https?|tg)://[^)\s]+)\s*\)", re.I)


def _links_to_buttons(raw):
    """A line made only of [Text](https://link) items becomes buttons (items after the first stay on the same row)."""
    out = []
    for line in (raw or "").split("\n"):
        if LINK_LINE_RE.match(line):
            items = LINK_RE_1.findall(line)
            line = "\n".join(f"[{t}](buttonurl://{u}{':same' if i else ''})" for i, (t, u) in enumerate(items))
        out.append(line)
    return "\n".join(out)


def md_from_entities(text, entities):
    """Keep Telegram's own formatting that plain text would lose:
    hidden links (text_link) -> [text](url) and premium emoji (custom_emoji) -> ![😀](emoji:ID)."""
    text = text or ""

    def wanted(e):
        return ((e.type == "text_link" and getattr(e, "url", None))
                or (e.type == "custom_emoji" and getattr(e, "custom_emoji_id", None)))

    ents = sorted((e for e in (entities or []) if wanted(e)), key=lambda e: e.offset)
    if not ents:
        return text
    b, out, pos = text.encode("utf-16-le"), [], 0          # entity offsets are UTF-16 code units
    for e in ents:
        if e.offset < pos:
            continue
        out.append(b[pos * 2:e.offset * 2].decode("utf-16-le"))
        label = b[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le")
        out.append(f"![{label}](emoji:{e.custom_emoji_id})" if e.type == "custom_emoji" else f"[{label}]({e.url})")
        pos = e.offset + e.length
    out.append(b[pos * 2:].decode("utf-16-le"))
    return "".join(out)


def visible_len(raw):
    """Length of a template as the user sees it (a premium emoji counts as its 1-2 emoji characters)."""
    return len(CUSTOM_EMOJI_MD.sub(r"\1", raw or ""))


def parse_buttons(raw, link_lines=False):
    """Split a message template into (text without button lines, button rows, error or None).

    link_lines=True (welcome/goodbye): a line that contains only [Text](https://...) links is treated as buttons too.
    """
    if link_lines:
        raw = _links_to_buttons(raw)
    rows, state = [], {"n": 0, "seen": 0, "err": None}

    def grab(m):
        state["seen"] += 1
        label, url = m.group(1), m.group(2)
        mods = set(re.findall(r"[a-z]+", m.group(3).lower()))
        if url.startswith("@"):
            url = "https://t.me/" + url[1:]
        if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
            url = "https://" + url
        if not re.match(r"^(https?|tg)://", url, re.I):
            state["err"] = state["err"] or f"Button “{label}”: links must start with http(s):// or tg://"
            return ""
        if state["n"] >= MAX_BUTTONS:
            state["err"] = state["err"] or f"Too many buttons (max {MAX_BUTTONS})."
            return ""
        style = next((x for x in BUTTON_STYLES if x in mods), None)
        b = Btn(label, url=url, **({"api_kwargs": {"style": style}} if style else {}))
        if "same" in mods and rows and len(rows[-1]) < BUTTONS_PER_ROW:
            rows[-1].append(b)
        else:
            rows.append([b])
        state["n"] += 1
        return ""

    text = BTN_RE.sub(grab, raw or "").strip()
    if not state["err"] and (raw or "").lower().count("buttonurl") > state["seen"]:
        state["err"] = "I couldn't read one of the buttons. " + BTN_FORMAT_HELP
    return text, rows, state["err"]


def build_message(raw, fill=None, link_lines=False):
    """Markdown + buttons + placeholders -> (html_text, markup|None)."""
    raw, rows, _ = parse_buttons(raw, link_lines)
    out = md_to_html(raw)
    for k, v in (fill or {}).items():
        out = out.replace("{" + k + "}", v)
    return out or "\u200b", (Markup(rows) if rows else None)


def fill_for(user, chat, count=None):
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return {
        "first": esc(user.first_name), "last": esc(user.last_name or ""),
        "fullname": esc(full),
        "username": esc("@" + user.username) if user.username else mention(user.id, user.first_name),
        "mention": mention(user.id, user.first_name), "id": str(user.id),
        "chatname": esc(chat.title or "this chat"), "count": str(count or ""),
    }


def now():
    return int(time.time())


def fmt_time(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def split_quoted(s):
    """'"hello world" reply text' -> ('hello world', 'reply text')."""
    s = s.strip()
    m = re.match(r'^"([^"]+)"\s*(.*)$', s, re.S)
    if m:
        return m.group(1), m.group(2).strip()
    parts = s.split(None, 1)
    return (parts[0], parts[1].strip() if len(parts) > 1 else "") if parts else ("", "")


def plain_text(msg):
    """Text/caption of a message, or '' when empty or when it is a /command."""
    text = (msg.text or msg.caption or "") if msg else ""
    return "" if re.match(r"^[/!]\w+", text) else text


# ───────────────────────── temporary notices ─────────────────────────
_BG_TASKS = set()
_COOLDOWN = {}


def cooldown_ok(key, seconds=30):
    """True at most once per `seconds` for a given key (used to avoid notice spam)."""
    t = time.monotonic()
    if len(_COOLDOWN) > 5000:
        _COOLDOWN.clear()
    if t - _COOLDOWN.get(key, -1e9) < seconds:
        return False
    _COOLDOWN[key] = t
    return True


async def temp_notice(ctx, chat_id, text, seconds=10, **kw):
    """Send a message and delete it again after `seconds`."""
    try:
        m = await ctx.bot.send_message(chat_id, text, **kw)
    except Exception:
        return

    async def _remove():
        await asyncio.sleep(seconds)
        try:
            await m.delete()
        except Exception:
            pass

    task = asyncio.get_running_loop().create_task(_remove())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


# ───────────────────────── logger ─────────────────────────
START_TIME = time.time()


async def user_photo(bot, uid):
    """file_id of a user's (or bot's) current profile photo, or None."""
    try:
        r = await bot.get_user_profile_photos(uid, limit=1)
        return r.photos[0][-1].file_id if r.total_count else None
    except Exception:
        return None


async def chat_photo(bot, chat_id):
    """file_id of a group's photo, or None."""
    try:
        c = await bot.get_chat(chat_id)
        return c.photo.big_file_id if c.photo else None
    except Exception:
        return None


async def send_log(bot, text, photo=None):
    """Post to the log chat (LOG_CHANNEL_ID), with a photo when given. Never raises."""
    if not LOG_CHANNEL:
        return
    try:
        if photo:
            try:
                return await bot.send_photo(LOG_CHANNEL, photo, caption=text[:1024])
            except Exception as e:
                log.warning("log photo failed, sending text only: %s", e)
        await bot.send_message(LOG_CHANNEL, text)
    except Exception as e:
        log.warning("could not write to log chat %s: %s", LOG_CHANNEL, e)


def fmt_uptime(seconds):
    d, r = divmod(int(seconds), 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return " ".join(x for x in (f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s") if x)


# ───────────────────────── known chats (broadcast targets) ─────────────────────────
_SEEN = set()


def track_chat(chat):
    """Remember every chat the bot talks in: private users go to bc_users, groups to bc_chats."""
    if chat.id in _SEEN:
        return False
    _SEEN.add(chat.id)
    scope = "bc_users" if chat.type == ChatType.PRIVATE else "bc_chats"
    if db.get(scope, chat.id) is None:
        db.put(scope, chat.id, chat.title or chat.full_name or "")
        return True      # first time we see it
    return False
