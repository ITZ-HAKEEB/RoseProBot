"""Tiny key/value store: every setting of the bot lives here, so nothing is lost on a restart.

Backends (first one that is configured wins):
  1. MongoDB   - set MONGO_URL (or MONGODB_URI / MONGO_URI). MongoDB Atlas free tier works great on Heroku.
  2. Postgres  - set DATABASE_URL (or DB_URL).
  3. SQLite    - local file bot.db, only for your own computer. Heroku's disk is WIPED on every restart, so on
                 Heroku the bot refuses to start without a real database (ALLOW_TEMP_DB=1 overrides, quick tests only).

Public API (same for all backends): get, put, delete, items, scope_keys, count, kind.
"""
import json
import logging
import os
import time

_log = logging.getLogger("lisa.db")

_mongo_url = (os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URI")
              or os.environ.get("MONGO_URI") or os.environ.get("MONGO_DB_URL") or "")
_sql_url = os.environ.get("DATABASE_URL") or os.environ.get("DB_URL") or ""

kind = ""        # "MongoDB" | "PostgreSQL" | "SQLite"
engine = None    # SQLAlchemy engine (only for Postgres / SQLite)

if _mongo_url:
    # ----------------------------------------------------------------------------------------- MongoDB
    try:
        from pymongo import MongoClient, ASCENDING
        from pymongo.errors import AutoReconnect, NetworkTimeout, ServerSelectionTimeoutError
    except ImportError:
        raise SystemExit("\n*** pymongo is not installed ***\nMONGO_URL is set but requirements.txt on this deploy has no pymongo.\n"
                         "Add the line  pymongo[srv]>=4.8,<5  to requirements.txt, push it, and redeploy.\n")

    kind = "MongoDB"
    _client = MongoClient(_mongo_url, serverSelectionTimeoutMS=15000, retryWrites=True, retryReads=True)
    try:
        _dbname = _client.get_default_database().name      # database named in the URL (.../mydb?...)
    except Exception:
        _dbname = os.environ.get("MONGO_DB_NAME", "lisa_bot")
    _col = _client[_dbname]["kv"]

    def _retry(fn):
        """Retry twice on a dropped connection / failover."""
        def wrapper(*a, **kw):
            for attempt in range(3):
                try:
                    return fn(*a, **kw)
                except (AutoReconnect, NetworkTimeout, ServerSelectionTimeoutError) as e:
                    if attempt == 2:
                        raise
                    _log.warning("MongoDB connection problem (%s), retrying", type(e).__name__)
                    time.sleep(0.5 * (attempt + 1))
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    _retry(lambda: _col.create_index([("scope", ASCENDING), ("k", ASCENDING)], unique=True))()
    _log.info("Using MongoDB database '%s'", _dbname)

    @_retry
    def get(scope, k, default=None):
        r = _col.find_one({"scope": scope, "k": str(k)}, {"v": 1})
        return json.loads(r["v"]) if r else default

    @_retry
    def put(scope, k, value):
        _col.update_one({"scope": scope, "k": str(k)}, {"$set": {"v": json.dumps(value)}}, upsert=True)

    @_retry
    def delete(scope, k):
        return _col.delete_one({"scope": scope, "k": str(k)}).deleted_count > 0

    @_retry
    def items(scope):
        return {d["k"]: json.loads(d["v"]) for d in _col.find({"scope": scope}, {"k": 1, "v": 1})}

    @_retry
    def scope_keys(scope):
        return [d["k"] for d in _col.find({"scope": scope}, {"k": 1})]

    @_retry
    def count():
        """Total number of stored settings (shown in the startup log so you can see data survived the restart)."""
        return _col.count_documents({})

else:
    # ------------------------------------------------------------------------------ Postgres / SQLite
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError

    _url = _sql_url
    if not _url:
        if os.environ.get("DYNO") and os.environ.get("ALLOW_TEMP_DB") != "1":
            raise SystemExit(
                "\n*** NO DATABASE CONFIGURED ***\n"
                "On Heroku the disk is wiped on every restart, so all settings (welcome, filters, warns, federations...)\n"
                "would be lost. Add a database first, then restart:\n"
                "  heroku config:set MONGO_URL=mongodb+srv://user:pass@cluster.mongodb.net/lisa_bot   (MongoDB Atlas)\n"
                "or  heroku addons:create heroku-postgresql:essential-0\n"
                "or  heroku config:set DATABASE_URL=postgresql://user:pass@host/dbname\n"
                "(set ALLOW_TEMP_DB=1 to start anyway with a temporary database)\n")
        _url = "sqlite:///bot.db"
    if _url.startswith("postgres://"):
        _url = _url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(_url, pool_pre_ping=True, pool_recycle=1800)
    kind = "PostgreSQL" if engine.dialect.name.startswith("postgres") else "SQLite"

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
