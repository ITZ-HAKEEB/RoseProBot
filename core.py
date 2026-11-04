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
from config import SUDO

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


def md_to_html(text):
    t = esc(text)
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
BTN_RE = re.compile(r"\[([^\]\n]+)\]\(buttonurl://([^)\s]+?)((?::(?:same|primary|success|danger|default))*)\)")
MAX_BUTTONS, BUTTONS_PER_ROW = 8, 4
BUTTON_STYLES = ("primary", "success", "danger")   # blue / green / red (Bot API 9.4+, newer Telegram clients)


def parse_buttons(raw):
    """Split a message template into (text without button lines, button rows, error or None)."""
    rows, state = [], {"n": 0, "err": None}

    def grab(m):
        label, url = m.group(1), m.group(2)
        mods = {x for x in m.group(3).split(":") if x}
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
    return text, rows, state["err"]


def build_message(raw, fill=None):
    """Markdown + buttons + placeholders -> (html_text, markup|None)."""
    raw, rows, _ = parse_buttons(raw)
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
