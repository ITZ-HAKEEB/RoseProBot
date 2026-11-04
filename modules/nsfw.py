"""Anti-NSFW filter for groups.

Two layers:
  1. Text layer (always works): keywords in messages / captions. A built-in list of high-signal terms plus
     your own words per chat (/addnsfw, /rmnsfw).
  2. Image layer (optional): photos, stickers, GIFs, videos and round videos are checked through the
     Sightengine nudity API via their preview image. Turn it on by setting the SIGHTENGINE_USER and
     SIGHTENGINE_SECRET environment variables. To use another provider, only edit `scan_image()`.

Admins are never touched. The bot needs the "delete messages" right (and "restrict members" for mute / ban).
"""
import asyncio
import re
from functools import lru_cache

import httpx
from telegram.constants import ChatType

import db
from config import NSFW_THRESHOLD, SIGHTENGINE_SECRET, SIGHTENGINE_USER
from core import (command, cooldown_ok, esc, is_admin, log, mention, register_help, reply, split_quoted, args_text,
                  target, temp_notice, watcher)
from modules.warns import ACTIONS, apply_action

register_help("nsfw", [
    ("nsfw", "Show or toggle the NSFW filter: /nsfw on|off. Removes adult keywords and (if configured) adult images"),
    ("nsfwaction", "Choose what happens to the sender: /nsfwaction delete|warn|mute|ban"),
    ("nsfwlist", "Show the custom words blocked in this chat"),
    ("addnsfw", "Block an extra word or phrase: /addnsfw &lt;word&gt;"),
    ("rmnsfw", "Stop blocking a custom word: /rmnsfw &lt;word&gt;"),
])

MEDIA_SCAN = bool(SIGHTENGINE_USER and SIGHTENGINE_SECRET)

# Built-in, deliberately short list of high-signal terms. Admins can extend it per chat.
DEFAULT_WORDS = (
    "porn", "porno", "pornhub", "xvideos", "xnxx", "xxx", "nsfw", "hentai", "onlyfans", "nudes",
    "sex video", "sex videos", "blowjob", "camgirl", "adult video", "adult videos",
)


def get_cfg(chat_id):
    return {"on": False, "action": "delete", "words": [], **db.get(f"c:{chat_id}", "nsfw", {})}


def save_cfg(chat_id, cfg):
    db.put(f"c:{chat_id}", "nsfw", cfg)


# ───────────────────────── text layer ─────────────────────────
@lru_cache(maxsize=256)
def _word_re(words):
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in words) + r")(?!\w)", re.I)


def text_hit(text, custom_words):
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    return bool(_word_re(tuple(DEFAULT_WORDS) + tuple(custom_words)).search(text))


# ───────────────────────── image layer ─────────────────────────
_SCANNED = {}  # file_unique_id -> score (avoids paying twice for the same file)


def media_ref(msg):
    """The part of a message that can be sent to an image classifier (a downloadable file object)."""
    if msg.photo:
        sizes = sorted(msg.photo, key=lambda p: p.width * p.height)
        return next((p for p in sizes if max(p.width, p.height) >= 640), sizes[-1])
    if msg.sticker:
        s = msg.sticker
        return s.thumbnail if (s.is_animated or s.is_video) else s
    if msg.animation:
        return msg.animation.thumbnail
    if msg.video:
        return msg.video.thumbnail
    if msg.video_note:
        return msg.video_note.thumbnail
    return None


async def scan_image(data):
    """Return a 0..1 'adult content' score for image bytes, or None if the scan failed.

    Provider: Sightengine nudity model. Swap this function to use a different service.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.sightengine.com/1.0/check.json",
                data={"models": "nudity-2.1", "api_user": SIGHTENGINE_USER, "api_secret": SIGHTENGINE_SECRET},
                files={"media": ("image.jpg", data)},
            )
        j = r.json()
    except Exception:
        log.exception("nsfw scan request failed")
        return None
    if j.get("status") != "success":
        log.warning("nsfw scan error: %s", j.get("error") or j)
        return None
    n = j.get("nudity", {})
    return max(float(n.get(k, 0) or 0) for k in ("sexual_activity", "sexual_display", "erotica"))


async def media_score(ref):
    if ref.file_unique_id in _SCANNED:
        return _SCANNED[ref.file_unique_id]
    f = await ref.get_file()
    score = await scan_image(bytes(await f.download_as_bytearray()))
    if score is not None:
        if len(_SCANNED) > 2000:
            _SCANNED.clear()
        _SCANNED[ref.file_unique_id] = score
    return score


# ───────────────────────── commands ─────────────────────────
@command("nsfw", "antinsfw")
async def cmd_nsfw(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    cfg = get_cfg(chat.id)
    if ctx.args and ctx.args[0].lower() in ("on", "off", "yes", "no"):
        if not await is_admin(chat, update.effective_user.id, ctx):
            return await reply(update, "Admins only.")
        cfg["on"] = ctx.args[0].lower() in ("on", "yes")
        save_cfg(chat.id, cfg)
        return await reply(update, f"NSFW filter turned {'on' if cfg['on'] else 'off'}.")
    await reply(update, f"<b>NSFW filter</b> in {esc(chat.title)}: <b>{'on' if cfg['on'] else 'off'}</b>\n"
                        f"Action: {cfg['action']}\nCustom words: {len(cfg['words'])}\n"
                        f"Image scanning: {'on' if MEDIA_SCAN else 'off (needs SIGHTENGINE_USER / SIGHTENGINE_SECRET)'}\n\n"
                        "Change with /nsfw on|off and /nsfwaction delete|warn|mute|ban.")


@command("nsfwaction")
async def cmd_nsfwaction(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or ctx.args[0].lower() not in ACTIONS:
        return await reply(update, "Usage: /nsfwaction " + "|".join(ACTIONS))
    cfg = get_cfg(chat.id)
    cfg["action"] = ctx.args[0].lower()
    save_cfg(chat.id, cfg)
    await reply(update, f"NSFW action set to {cfg['action']}.")


@command("nsfwlist")
async def cmd_nsfwlist(update, ctx):
    chat = await target(update, ctx, admin=False)
    if not chat:
        return
    words = get_cfg(chat.id)["words"]
    await reply(update, "<b>Custom NSFW words</b>\n\n" + "\n".join(f"• <code>{esc(w)}</code>" for w in words)
                if words else "No custom words. The built-in list is always active while the filter is on.")


@command("addnsfw")
async def cmd_addnsfw(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    word, _ = split_quoted(args_text(update.effective_message))
    word = word.lower().strip()
    if not word:
        return await reply(update, 'Usage: /addnsfw &lt;word&gt;  (or  /addnsfw "two words")')
    cfg = get_cfg(chat.id)
    if word not in cfg["words"]:
        cfg["words"].append(word)
    save_cfg(chat.id, cfg)
    await reply(update, f"Blocked: <code>{esc(word)}</code>")


@command("rmnsfw")
async def cmd_rmnsfw(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    word, _ = split_quoted(args_text(update.effective_message))
    cfg = get_cfg(chat.id)
    if word.lower().strip() in cfg["words"]:
        cfg["words"].remove(word.lower().strip())
        save_cfg(chat.id, cfg)
        return await reply(update, f"No longer blocked: <code>{esc(word)}</code>")
    await reply(update, "That word isn't in the custom list.")


# ───────────────────────── watcher ─────────────────────────
@watcher(50)
async def nsfw_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type == ChatType.PRIVATE:
        return
    cfg = db.get(f"c:{chat.id}", "nsfw")
    if not cfg or not cfg.get("on"):
        return
    text = msg.text or msg.caption or ""
    hit = bool(text) and text_hit(text, cfg.get("words", []))
    ref = None if hit or not MEDIA_SCAN else media_ref(msg)
    if not hit and ref is None:
        return
    if await is_admin(chat, user.id, ctx):
        return
    if not hit:
        try:
            score = await media_score(ref)
        except Exception:
            log.exception("nsfw media check failed")
            return
        if score is None or score < NSFW_THRESHOLD:
            return
    try:
        await msg.delete()
    except Exception:
        pass
    if not cooldown_ok((chat.id, user.id, "nsfw")):
        return True
    action = cfg.get("action", "delete")
    try:
        out = await apply_action(ctx, chat, user, action, "NSFW content")
    except Exception:
        log.exception("nsfw action %s failed in %s", action, chat.id)
        await temp_notice(ctx, chat.id, "⚠️ I need the right to delete messages and restrict / ban members.")
        return True
    if out:
        await ctx.bot.send_message(chat.id, out)
    else:
        await temp_notice(ctx, chat.id, f"🔞 {mention(user.id, user.first_name)}, NSFW content isn't allowed in this group.")
    return True
