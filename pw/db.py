"""SQLite storage: what's in the store, and every change we've seen (the change log the site and bots read)."""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS ships (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT, image TEXT, category TEXT,
  price INTEGER, list_price INTEGER, available INTEGER, limited INTEGER, level TEXT,
  listed INTEGER NOT NULL, misses INTEGER NOT NULL DEFAULT 0,
  first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, listed_since INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, ship_id TEXT, data TEXT NOT NULL,
  posted TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS watches (
  platform TEXT NOT NULL, user_id TEXT NOT NULL, query TEXT NOT NULL, created INTEGER NOT NULL,
  PRIMARY KEY (platform, user_id, query)
);
CREATE TABLE IF NOT EXISTS catalog (
  name TEXT PRIMARY KEY, key TEXT NOT NULL, maker TEXT, status TEXT, focus TEXT, size TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS loaners (ship TEXT PRIMARY KEY, keys TEXT NOT NULL, loaners TEXT NOT NULL);
"""


def connect(path, check_same_thread=True):
    db = sqlite3.connect(path, check_same_thread=check_same_thread)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(ships)")}
    if "qty" not in cols:
        db.execute("ALTER TABLE ships ADD COLUMN qty INTEGER")
    return db


def known(db):
    rows = db.execute("SELECT * FROM ships").fetchall()
    return {r["id"]: {**dict(r), "listed": bool(r["listed"]), "available": bool(r["available"]),
                      "limited": bool(r["limited"])} for r in rows}


def save(db, updates, events, now=None):
    """Write one check's results in a single transaction."""
    now = int(now or time.time())
    with db:
        for sid, f in updates.items():
            exists = db.execute("SELECT listed FROM ships WHERE id=?", (sid,)).fetchone()
            if exists is None:
                db.execute("""INSERT INTO ships (id, name, url, image, category, price, list_price, available, limited,
                              level, qty, listed, misses, first_seen, last_seen, listed_since)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?)""",
                           (sid, f["name"], f["url"], f["image"], f["category"], f["price"], f["list_price"],
                            f["available"], f["limited"], f["level"], f.get("qty"), now, now, now))
                continue
            if f.get("listed") and not exists["listed"]:
                f = {**f, "listed_since": now}
            if f.get("listed"):
                f = {**f, "last_seen": now}
            cols = ", ".join(f"{k}=?" for k in f)
            db.execute(f"UPDATE ships SET {cols} WHERE id=?", (*f.values(), sid))
        for e in events:
            db.execute("INSERT INTO events (ts, kind, ship_id, data) VALUES (?,?,?,?)",
                       (now, e["kind"], e.get("id"), json.dumps(e)))


def get_state(db, key, default=None):
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(db, key, value):
    with db:
        db.execute("INSERT INTO state (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))


def add_event(db, kind, data, now=None):
    with db:
        db.execute("INSERT INTO events (ts, kind, ship_id, data) VALUES (?,?,?,?)",
                   (int(now or time.time()), kind, None, json.dumps({"kind": kind, **data})))
