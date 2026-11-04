"""Tiny key/value store: every setting of the bot lives here, so nothing is lost on a restart.

Postgres is used when DATABASE_URL (or DB_URL) is set - Heroku Postgres, or any external Postgres such as
Neon / Supabase / ElephantSQL. Without it the bot falls back to a local SQLite file, which is fine on your own
computer but is WIPED on every Heroku restart (the Heroku disk is temporary), so on Heroku the bot refuses to
start without a real database (set ALLOW_TEMP_DB=1 to override, e.g. for a quick test).
"""
import json
import logging
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

_log = logging.getLogger("lisa.db")

_url = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL") or ""
if not _url:
    if os.environ.get("DYNO") and os.environ.get("ALLOW_TEMP_DB") != "1":
        raise SystemExit(
            "\n*** NO DATABASE CONFIGURED ***\n"
            "On Heroku the disk is wiped on every restart, so all settings (welcome, filters, warns, federations...)\n"
            "would be lost. Add a database first, then restart:\n"
            "  heroku addons:create heroku-postgresql:essential-0\n"
            "or use a free external Postgres (Neon / Supabase) and run:\n"
            "  heroku config:set DATABASE_URL=postgresql://user:pass@host/dbname\n"
            "(set ALLOW_TEMP_DB=1 to start anyway with a temporary database)\n")
    _url = "sqlite:///bot.db"
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)

engine = create_engine(_url, pool_pre_ping=True, pool_recycle=1800)


def _retry(fn):
    """Run a DB call; retry twice on a dropped connection (Postgres restarts / idle timeouts)."""
    def wrapper(*a, **kw):
        for attempt in range(3):
            try:
                return fn(*a, **kw)
            except DBAPIError as e:
                if attempt == 2 or not getattr(e, "connection_invalidated", False) and "connection" not in str(e).lower():
                    raise
                _log.warning("database connection problem (%s), retrying", type(e).__name__)
                engine.dispose()
                time.sleep(0.5 * (attempt + 1))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

with engine.begin() as c:
    c.execute(text(
        "CREATE TABLE IF NOT EXISTS kv ("
        "scope VARCHAR(100) NOT NULL, k VARCHAR(250) NOT NULL, v TEXT NOT NULL, "
        "PRIMARY KEY (scope, k))"
    ))


@_retry
def get(scope, k, default=None):
    with engine.connect() as c:
        r = c.execute(text("SELECT v FROM kv WHERE scope=:s AND k=:k"), {"s": scope, "k": str(k)}).first()
    return json.loads(r[0]) if r else default


@_retry
def put(scope, k, value):
    p = {"s": scope, "k": str(k), "v": json.dumps(value)}
    with engine.begin() as c:
        n = c.execute(text("UPDATE kv SET v=:v WHERE scope=:s AND k=:k"), p).rowcount
        if not n:
            c.execute(text("INSERT INTO kv (scope,k,v) VALUES (:s,:k,:v)"), p)


@_retry
def delete(scope, k):
    with engine.begin() as c:
        return c.execute(text("DELETE FROM kv WHERE scope=:s AND k=:k"), {"s": scope, "k": str(k)}).rowcount > 0


@_retry
def items(scope):
    with engine.connect() as c:
        rows = c.execute(text("SELECT k, v FROM kv WHERE scope=:s"), {"s": scope}).all()
    return {k: json.loads(v) for k, v in rows}


@_retry
def scope_keys(scope):
    with engine.connect() as c:
        return [r[0] for r in c.execute(text("SELECT k FROM kv WHERE scope=:s"), {"s": scope}).all()]


@_retry
def count():
    """Total number of stored settings (shown in the startup log so you can see data survived the restart)."""
    with engine.connect() as c:
        return c.execute(text("SELECT COUNT(*) FROM kv")).scalar() or 0
