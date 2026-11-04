"""Tiny key/value store. Postgres on Heroku (DATABASE_URL), SQLite locally."""
import json
import os

from sqlalchemy import create_engine, text

_url = os.environ.get("DATABASE_URL", "sqlite:///bot.db")
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)

engine = create_engine(_url, pool_pre_ping=True)

with engine.begin() as c:
    c.execute(text(
        "CREATE TABLE IF NOT EXISTS kv ("
        "scope VARCHAR(100) NOT NULL, k VARCHAR(250) NOT NULL, v TEXT NOT NULL, "
        "PRIMARY KEY (scope, k))"
    ))


def get(scope, k, default=None):
    with engine.connect() as c:
        r = c.execute(text("SELECT v FROM kv WHERE scope=:s AND k=:k"), {"s": scope, "k": str(k)}).first()
    return json.loads(r[0]) if r else default


def put(scope, k, value):
    p = {"s": scope, "k": str(k), "v": json.dumps(value)}
    with engine.begin() as c:
        n = c.execute(text("UPDATE kv SET v=:v WHERE scope=:s AND k=:k"), p).rowcount
        if not n:
            c.execute(text("INSERT INTO kv (scope,k,v) VALUES (:s,:k,:v)"), p)


def delete(scope, k):
    with engine.begin() as c:
        return c.execute(text("DELETE FROM kv WHERE scope=:s AND k=:k"), {"s": scope, "k": str(k)}).rowcount > 0


def items(scope):
    with engine.connect() as c:
        rows = c.execute(text("SELECT k, v FROM kv WHERE scope=:s"), {"s": scope}).all()
    return {k: json.loads(v) for k, v in rows}


def scope_keys(scope):
    with engine.connect() as c:
        return [r[0] for r in c.execute(text("SELECT k FROM kv WHERE scope=:s"), {"s": scope}).all()]
