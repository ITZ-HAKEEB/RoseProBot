# Lisa Group Manager Bot

LisaProBot-style Telegram group management bot (Python, python-telegram-bot 21).

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME)

> Deploy button kaam karne ke liye: is folder ko apne GitHub repo me push karo (public repo), phir upar link me
> `YOUR_GITHUB_USERNAME/YOUR_REPO_NAME` apne repo se replace karo.

## Features
- **Federation**: /newfed /joinfed /leavefed /fban /unfban /fbanlist /fpromote /fdemote /fedadmins /fedchats /fedinfo /myfeds /renamefed /delfed
- **Filters**: /filter /filters /stop
- **Locks**: /lock /unlock /locks /locktype (24 types)
- **Notes**: /save /get /notes /clear and `#name`
- **Reports**: /report and `@admin`
- **User**: /about /admins /bug /chatinfo /connect /connections /disconnect /disabled /help /id /kickme /lang /ping /rules /start /userinfo /warns /warnsettings
- **Welcome**: /welcome /setwelcome /resetwelcome /goodbye /setgoodbye /resetgoodbye /markdownhelp — text or media (photo, video, GIF, sticker, voice, document), markdown incl. underline and spoiler, placeholders, up to 8 inline buttons (4 per row) with colours `:primary` `:success` `:danger` (needs a recent Telegram app, Feb 2026+; older apps show normal buttons)
- **BioLink**: /biolink /biolinkaction /biolinklimit /biolinkallow /biolinkunallow /biolinkallowed — users with a link or @username in their bio are warned 3 times (configurable), then muted (or banned). Warning messages have Updates / Support buttons; a muted user can tap "I removed it" to get unmuted once the bio is clean
- **NSFW**: /nsfw /nsfwaction /nsfwlist /addnsfw /rmnsfw — keyword filter (built-in list + your own words) and optional image scanning
- **Moderation (extra)**: /ban /unban /kick /mute /unmute /warn /resetwarns /setwarnlimit /setwarnaction /setwarnexpiry /setrules /disable /enable
- Commands work with both `/` and `!`. Settings can be managed from PM via /connect.

## Project layout
```
bot.py            entry point (wires everything together)
config.py         environment variables
core.py           shared helpers + registries (commands, help, watchers)
db.py             key/value storage (Postgres / SQLite)
modules/
  help.py  userinfo.py  connections.py  rules.py  moderation.py  warns.py
  federation.py  keyword_filters.py  locks.py  notes.py  reports.py  welcome.py
  biolink.py  nsfw.py
```
Each file in `modules/` is one feature. To add a feature: create a file there, use `@command(...)`, `register_help(...)`
and (for message filters) `@watcher(priority)` from `core.py`, then add it to `modules/__init__.py`.

## BioLink / NSFW notes
- Both are **off by default**; turn them on per group with `/biolink on` and `/nsfw on` (admins). Admins are never touched.
- The bot needs *Delete messages* (and *Restrict members* for mute / ban).
- BioLink reads the user's bio via the Bot API (cached 10 min). Telegram only returns a bio for users the bot can see, so
  a missing bio is treated as "no link".
- NSFW images: set `SIGHTENGINE_USER` and `SIGHTENGINE_SECRET` (and optionally `NSFW_THRESHOLD`, default 0.7). Without them
  only text / captions are checked.

## Deploy on Heroku
1. Create a bot with @BotFather, copy the token.
2. Click the Deploy button, fill `BOT_TOKEN` and `OWNER_ID` (+ optional SUPPORT_URL / UPDATES_URL).
3. After deploy: **Resources** tab → turn **worker** ON (web dyno is not used).
4. Add the bot to your group as admin (delete messages, ban users, invite users).

CLI alternative:
```
heroku create
heroku addons:create heroku-postgresql
heroku config:set BOT_TOKEN=xxx OWNER_ID=123
git push heroku main
heroku ps:scale worker=1
```

## Local run
```
pip install -r requirements.txt
cp .env.example .env   # export the variables
python bot.py
```
Data is stored in Postgres on Heroku (SQLite `bot.db` locally).
