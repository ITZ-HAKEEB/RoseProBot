"""Anti-NSFW filter for groups. Works fully offline, no API key needed.

Two layers:
  1. Text layer: keywords in messages / captions. A built-in list of high-signal terms plus your own words per
     chat (/addnsfw, /rmnsfw).
  2. Image layer: photos, stickers, GIFs, videos, round videos and image files are checked LOCALLY with the
     NudeNet model (runs on the bot's own CPU, nothing is sent anywhere). For videos / GIFs / animated stickers
     the preview frame is checked. If the `nudenet` package is missing the image layer is simply off.
     (Optional: if you set SIGHTENGINE_USER / SIGHTENGINE_SECRET and NudeNet is not installed, Sightengine is used.)

Admin text is never touched (so admin commands keep working), but NSFW pictures / stickers of admins are deleted too (no warn / mute / ban for admins). The bot needs the "delete messages" right (and "restrict members" for mute / ban).
"""
import asyncio
import importlib.util
import io
import os
import re
import tempfile
import threading
from functools import lru_cache

import httpx
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import NSFW_THRESHOLD, SIGHTENGINE_SECRET, SIGHTENGINE_USER, SUPPORT_URL, UPDATES_URL
from core import (command, cooldown_ok, esc, is_admin, log, mention, register_help, reply, split_quoted, args_text,
                  target, temp_notice, watcher)
from modules.warns import ACTIONS, apply_action

register_help("nsfw", [
    ("nsfw", "Show or toggle the NSFW filter: /nsfw on|off. Removes adult keywords and (if configured) adult images"),
    ("nsfwaction", "Choose what happens to the sender: /nsfwaction delete|warn|mute|ban"),
    ("nsfwlevel", "How strict the image check is: /nsfwlevel strict|normal. Strict also removes partly nude / swimwear / lingerie pictures"),
    ("nsfwtest", "Admins: reply to a photo / sticker with /nsfwtest to see what the scanner finds in it"),
    ("nsfwlist", "Show the custom words blocked in this chat"),
    ("addnsfw", "Block an extra word or phrase: /addnsfw &lt;word&gt;"),
    ("rmnsfw", "Stop blocking a custom word: /rmnsfw &lt;word&gt;"),
])

LOCAL_SCAN = importlib.util.find_spec("nudenet") is not None and importlib.util.find_spec("PIL") is not None
API_SCAN = bool(SIGHTENGINE_USER and SIGHTENGINE_SECRET)
MEDIA_SCAN = LOCAL_SCAN or API_SCAN

# Built-in, deliberately short list of high-signal terms. Admins can extend it per chat.
DEFAULT_WORDS = (
    "porn", "porno", "pornhub", "xvideos", "xnxx", "xxx", "nsfw", "hentai", "onlyfans", "nudes",
    "sex video", "sex videos", "blowjob", "camgirl", "adult video", "adult videos",
    "xhamster", "redtube", "brazzers", "chudai", "sexchat", "sex chat", "nude", "naked pics", "nude pics",
)


def get_cfg(chat_id):
    return {"on": False, "action": "delete", "words": [], "level": "strict", **db.get(f"c:{chat_id}", "nsfw", {})}


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
    """The part of a message that can be checked as an image (a downloadable file object), or None."""
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
    d = msg.document                      # a picture sent "as file"
    if d and (d.mime_type or "").startswith("image/") and (d.file_size or 0) < 8_000_000:
        return d
    return None


# --- local model (NudeNet) ---
_DET = None
_DET_ERR = None
_DET_LOCK = threading.Lock()


def _load_detector():
    global _DET, _DET_ERR
    if _DET is not None or _DET_ERR:
        return _DET
    with _DET_LOCK:
        if _DET is None and not _DET_ERR:
            try:
                from nudenet import NudeDetector
                _DET = NudeDetector()
                log.info("NSFW: local NudeNet model loaded")
            except Exception as e:
                _DET_ERR = f"{type(e).__name__}: {e}"
                log.error("NSFW: could not load NudeNet (%s): image scanning is OFF", _DET_ERR)
    return _DET


def _label_is_adult(label):
    """Exposed genitalia / buttocks / anus / female breast. Covered parts, belly, feet, male chest are ignored."""
    l = str(label).upper()
    if "EXPOSED" not in l or not any(k in l for k in ("GENITALIA", "BUTTOCKS", "ANUS", "BREAST")):
        return False
    if "BREAST" in l and (l.startswith("MALE") or l.endswith("_M")):
        return False
    return True


def adult_score(detections):
    return max((float(d.get("score", 0) or 0) for d in detections if _label_is_adult(d.get("class", ""))), default=0.0)


# Parts that are covered but suggest swimwear / lingerie: a picture showing 3 of these 4 together is "revealing".
REVEALING = ("FEMALE_BREAST_COVERED", "FEMALE_GENITALIA_COVERED", "BUTTOCKS_COVERED", "BELLY_EXPOSED")
STRICT_EXPOSED = min(0.3, NSFW_THRESHOLD)


def make_info(detections):
    exposed = adult_score(detections)
    best = {}
    for d in detections:
        c = str(d.get("class", "")).upper()
        best[c] = max(best.get(c, 0.0), float(d.get("score", 0) or 0))
    revealing = sum(1 for k in REVEALING if best.get(k, 0) >= 0.4) >= 3
    seen = sorted(((round(v, 2), k) for k, v in best.items() if v >= 0.2), reverse=True)
    return {"exposed": exposed, "revealing": revealing, "seen": seen}


def is_adult(info, level="strict"):
    if level == "strict":
        return info["exposed"] >= STRICT_EXPOSED or info["revealing"]
    return info["exposed"] >= NSFW_THRESHOLD


def _scan_local_sync(data):
    det = _load_detector()
    if det is None:
        return None
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):                       # transparent stickers: put them on white
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        img.save(path, "JPEG", quality=92)
        return make_info(det.detect(path))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _scan_sightengine(data):
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
    return {"exposed": max(float(n.get(k, 0) or 0) for k in ("sexual_activity", "sexual_display", "erotica")),
            "revealing": False, "seen": []}


async def scan_image(data):
    """{"exposed": 0..1, "revealing": bool, "seen": [...]} for image bytes, or None if the scan was not possible."""
    if LOCAL_SCAN:
        try:
            score = await asyncio.to_thread(_scan_local_sync, data)
        except Exception:
            log.exception("nsfw local scan failed")
            score = None
        if score is not None or not API_SCAN:
            return score
    if API_SCAN:
        return await _scan_sightengine(data)
    return None


async def media_info(ref):
    if ref.file_unique_id in _SCANNED:
        return _SCANNED[ref.file_unique_id]
    f = await ref.get_file()
    info = await scan_image(bytes(await f.download_as_bytearray()))
    if info is not None:
        if len(_SCANNED) > 2000:
            _SCANNED.clear()
        _SCANNED[ref.file_unique_id] = info
    return info


async def preload():
    """Load the model at startup so a problem shows up in the start message instead of failing silently."""
    if LOCAL_SCAN:
        det = await asyncio.to_thread(_load_detector)
        return "✅ local NudeNet loaded" if det else f"❌ NudeNet failed: {_DET_ERR}"
    return "✅ Sightengine API" if API_SCAN else "❌ off (nudenet not installed)"


def model_state():
    if LOCAL_SCAN:
        return "on (local, no API)" if _DET_ERR is None else f"BROKEN: {_DET_ERR}"
    return "on (Sightengine)" if API_SCAN else "off (nudenet is not installed)"


# ───────────────────────── sticker packs ─────────────────────────
_PACKS = {}
_PACK_RE = re.compile(r"(?<![a-z0-9])(nsfw|porn|porno|hentai|sex|nude|nudes|naked|xxx|lewd|ecchi|boobs|adult)(?![a-z0-9])", re.I)


async def sticker_pack_hit(ctx, st, custom_words):
    """A sticker from a pack whose name / title says it is adult is removed without even looking at the picture."""
    name = st.set_name
    if not name:
        return False
    if name not in _PACKS:
        title = ""
        try:
            title = (await ctx.bot.get_sticker_set(name)).title or ""
        except Exception:
            pass
        if len(_PACKS) > 2000:
            _PACKS.clear()
        _PACKS[name] = f"{name} {title}".replace("_", " ")
    t = _PACKS[name]
    return bool(_PACK_RE.search(t)) or text_hit(t, custom_words)


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
                        f"Image scanning: {model_state()}\nStrictness: {cfg['level']}\n\n"
                        "Change with /nsfw on|off, /nsfwaction delete|warn|mute|ban and /nsfwlevel strict|normal.")


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


@command("nsfwlevel")
async def cmd_nsfwlevel(update, ctx):
    chat = await target(update, ctx)
    if not chat:
        return
    if not ctx.args or ctx.args[0].lower() not in ("strict", "normal"):
        return await reply(update, "Usage: /nsfwlevel strict|normal\n<b>strict</b>: also removes partly nude, swimwear and "
                                   "lingerie pictures. <b>normal</b>: only clearly nude ones.")
    cfg = get_cfg(chat.id)
    cfg["level"] = ctx.args[0].lower()
    save_cfg(chat.id, cfg)
    await reply(update, f"NSFW strictness set to {cfg['level']}.")


@command("nsfwtest")
async def cmd_nsfwtest(update, ctx):
    chat, msg = update.effective_chat, update.effective_message
    if not await is_admin(chat, update.effective_user.id, ctx):
        return await reply(update, "Admins only.")
    rep_msg = msg.reply_to_message
    ref = media_ref(rep_msg) if rep_msg else None
    if ref is None:
        return await reply(update, "Reply to a photo / sticker / GIF / video with /nsfwtest.")
    if not MEDIA_SCAN:
        return await reply(update, f"Image scanning: {model_state()}")
    info = await media_info(ref)
    if info is None:
        return await reply(update, f"❌ The scan failed. Image scanning: {model_state()}\nCheck the bot logs.")
    level = get_cfg(chat.id)["level"]
    seen = "\n".join(f"• {k}: {v}" for v, k in info["seen"][:10]) or "nothing found"
    await reply(update, f"<b>Scan result</b> (strictness: {level})\nExposed score: {info['exposed']:.2f}\n"
                        f"Revealing (swimwear/lingerie): {'yes' if info['revealing'] else 'no'}\n"
                        f"Would be removed: <b>{'YES' if is_adult(info, level) else 'no'}</b>\n\n{seen}")


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
def _buttons():
    return Markup([[Btn("📢 Updates", url=UPDATES_URL), Btn("💬 Support", url=SUPPORT_URL)]])


@watcher(50)
async def nsfw_watcher(update, ctx):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if chat.type == ChatType.PRIVATE:
        return
    cfg = db.get(f"c:{chat.id}", "nsfw")
    if not cfg or not cfg.get("on"):
        return
    words, level = cfg.get("words", []), cfg.get("level", "strict")
    text = msg.text or msg.caption or ""
    hit = bool(text) and text_hit(text, words)
    ref = media_ref(msg) if MEDIA_SCAN else None
    pack = bool(msg.sticker) and await sticker_pack_hit(ctx, msg.sticker, words)
    if not (hit or pack) and ref is None:
        return
    admin = await is_admin(chat, user.id, ctx)
    if admin:
        hit = False                      # admin text / commands are left alone; their pictures and stickers are not
        if not pack and ref is None:
            return
    if not (hit or pack):
        try:
            info = await media_info(ref)
        except Exception:
            log.exception("nsfw media check failed")
            return
        if info is None:
            return
        verdict = is_adult(info, level)
        log.info("nsfw scan in %s: exposed=%.2f revealing=%s level=%s -> %s", chat.id, info["exposed"],
                 info["revealing"], level, "REMOVE" if verdict else "ok")
        if not verdict:
            return
    try:
        await msg.delete()
    except Exception:
        pass
    if admin:                            # deleted, but an admin is never warned / muted / banned
        if cooldown_ok((chat.id, user.id, "nsfw")):
            await temp_notice(ctx, chat.id, f"🔞 NSFW content of {mention(user.id, user.first_name)} was removed.",
                              10, reply_markup=_buttons())
        return True
    if not cooldown_ok((chat.id, user.id, "nsfw")):
        return True
    action = cfg.get("action", "delete")
    try:
        out = await apply_action(ctx, chat, user, action, "NSFW content")
    except Exception:
        log.exception("nsfw action %s failed in %s", action, chat.id)
        await temp_notice(ctx, chat.id, "⚠️ I need the right to delete messages and restrict / ban members.",
                          reply_markup=_buttons())
        return True
    if out:
        await ctx.bot.send_message(chat.id, out, reply_markup=_buttons())
    else:
        await temp_notice(ctx, chat.id, f"🔞 {mention(user.id, user.first_name)}, NSFW content isn't allowed in this group.",
                          15, reply_markup=_buttons())
    return True
