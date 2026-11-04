
"""Premium Help Menu and Start Module."""

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.constants import ChatType

import db
from config import SUPPORT_URL, UPDATES_URL
from core import (
    HELP,
    build_message,
    callback,
    command,
    esc,
    mention,
    reply,
    send_log,
)


HELP_ORDER = [
    "federation",
    "filters",
    "locks",
    "notes",
    "reports",
    "user",
    "welcome",
    "moderation",
    "biolink",
    "nsfw",
    "owner",
]

LABELS = {
    "nsfw": "ɴꜱꜰᴡ",
    "biolink": "ʙɪᴏʟɪɴᴋ",
}

HELP_HEADER = (
    "✦ ᴘʀᴇᴍɪᴜᴍ ʜᴇʟᴘ ᴍᴇɴᴜ ✦\n\n"
    "➻ ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ꜰɪɴᴅ ᴀʟʟ ʙᴏᴛ ᴄᴏᴍᴍᴀɴᴅꜱ.\n"
    "➻ ᴄʜᴏᴏꜱᴇ ᴀ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ.\n\n"
    "✧ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ ᴡᴏʀᴋ ᴡɪᴛʜ: / !"
)


def premium_font(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    styled = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
    )
    return str(text).translate(str.maketrans(normal, styled))


def help_sections():
    names = [s for s in HELP_ORDER if s in HELP]
    names.extend(s for s in HELP if s not in HELP_ORDER)
    return names


def help_text(section):
    lines = [
        f"✦ {premium_font(section)} ✦",
        "",
    ]

    for name, desc in HELP[section]:
        command_name = premium_font(name)
        description = premium_font(desc)

        if " " not in name:
            lines.append(f"➻ /{command_name} — {description}")
        else:
            lines.append(f"➻ {command_name} — {description}")

    return "\n".join(lines)


def help_markup():
    names = help_sections()

    rows = [
        [
            Btn(
                LABELS.get(s, premium_font(s.title())),
                callback_data=f"help:{s}",
            )
            for s in names[i:i + 2]
        ]
        for i in range(0, len(names), 2)
    ]

    rows.append([
        Btn("✖ ᴄʟᴏꜱᴇ", callback_data="help:close")
    ])

    return Markup(rows)


@callback(r"^help:")
async def help_cb(update, ctx):
    q = update.callback_query
    arg = q.data.split(":", 1)[1]

    await q.answer()

    if arg == "close":
        await q.message.delete()

    elif arg == "back":
        await q.message.edit_text(
            HELP_HEADER,
            reply_markup=help_markup(),
        )

    elif arg in HELP:
        await q.message.edit_text(
            help_text(arg),
            reply_markup=Markup([
                [Btn("⬅ ʙᴀᴄᴋ", callback_data="help:back")]
            ]),
        )


@command("help")
async def cmd_help(update, ctx):
    if update.effective_chat.type != ChatType.PRIVATE:
        kb = Markup([
            [
                Btn(
                    "✦ ᴏᴘᴇɴ ʜᴇʟᴘ ✦",
                    url=f"https://t.me/{ctx.bot.username}?start=help",
                )
            ]
        ])

        return await reply(
            update,
            "➻ ᴄᴏɴᴛᴀᴄᴛ ᴍᴇ ɪɴ ᴘʀɪᴠᴀᴛᴇ ꜰᴏʀ ᴛʜᴇ "
            "ꜰᴜʟʟ ᴄᴏᴍᴍᴀɴᴅ ʟɪꜱᴛ.",
            reply_markup=kb,
        )

    await reply(
        update,
        HELP_HEADER,
        reply_markup=help_markup(),
    )


@command("start")
async def cmd_start(update, ctx):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != ChatType.PRIVATE:
        return await reply(
            update,
            "✦ ɪ'ᴍ ᴀʟɪᴠᴇ! ᴜꜱᴇ /help ɪɴ ᴘʀɪᴠᴀᴛᴇ.",
        )

    payload = ctx.args[0] if ctx.args else ""

    # Private start logger
    uname = f"@{esc(user.username)}" if user.username else "—"

    await send_log(
        ctx.bot,
        f"👤 <b>ᴜꜱᴇʀ ꜱᴛᴀʀᴛᴇᴅ ᴛʜᴇ ʙᴏᴛ</b>\n"
        f"ɴᴀᴍᴇ: {mention(user.id, user.full_name)}\n"
        f"ᴜꜱᴇʀɴᴀᴍᴇ: {uname}\n"
        f"ɪᴅ: <code>{user.id}</code>"
        + (
            f"\nᴘᴀʏʟᴏᴀᴅ: <code>{esc(payload)}</code>"
            if payload else ""
        ),
    )

    # Help deep link
    if payload == "help":
        return await reply(
            update,
            HELP_HEADER,
            reply_markup=help_markup(),
        )

    # Group rules deep link
    if payload.startswith("rules_"):
        cid = payload[6:]
        rules = db.get(f"c:{cid}", "rules")

        if not rules:
            return await reply(
                update,
                "✦ ᴛʜɪꜱ ᴄʜᴀᴛ ʜᴀꜱ ɴᴏ ʀᴜʟᴇꜱ ꜱᴇᴛ ʏᴇᴛ.",
            )

        txt, kb = build_message(rules)

        return await reply(
            update,
            "✦ ɢʀᴏᴜᴘ ʀᴜʟᴇꜱ ✦\n\n" + txt,
            reply_markup=kb,
        )

    # Premium START message
    text = (
        f"✦ ʜᴇʟʟᴏ {mention(user.id, user.first_name)}! ✦ 👋\n\n"
        "ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ʙᴏᴛ! ✨\n\n"
        "ᴘʟᴇᴀꜱᴇ ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ "
        "ᴛᴏ ɢᴇᴛ ꜱᴛᴀʀᴛᴇᴅ. 💫"
    )

    kb = Markup([
        [
            Btn(
                "➕ ᴀᴅᴅ ᴍᴇ ᴛᴏ ɢʀᴏᴜᴘ",
                url=(
                    f"https://t.me/{ctx.bot.username}"
                    "?startgroup=true&admin="
                    "delete_messages+restrict_members+pin_messages+invite_users"
                ),
            )
        ],
        [
            Btn("✦ ꜱᴜᴘᴘᴏʀᴛ ✦", url=SUPPORT_URL),
            Btn("✦ ᴜᴘᴅᴀᴛᴇꜱ ✦", url=UPDATES_URL),
        ],
        [
            Btn(
                "❖ ʜᴇʟᴘ ᴍᴇɴᴜ ❖",
                callback_data="help:back",
            )
        ],
    ])

    await reply(
        update,
        text,
        reply_markup=kb,
    )
