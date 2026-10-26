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
  name TEXT PRIMARY KEY, key TEXT NOT NULL, maker TEXT, maker_code TEXT, status TEXT, focus TEXT, type TEXT,
  size TEXT, min_crew INTEGER, max_crew INTEGER, cargo REAL, length REAL, image TEXT, url TEXT, mid TEXT
);
CREATE TABLE IF NOT EXISTS loaners (ship TEXT PRIMARY KEY, keys TEXT NOT NULL, loaners TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS servers (
  platform TEXT NOT NULL, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, role_id TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '', added INTEGER NOT NULL,
  PRIMARY KEY (platform, guild_id)
);
CREATE TABLE IF NOT EXISTS ingame (
  mid TEXT PRIMARY KEY, uuid TEXT, claim REAL, expedite REAL, expedite_cost REAL, version TEXT,
  history TEXT NOT NULL, buy TEXT NOT NULL, rent TEXT NOT NULL, name TEXT, weapons TEXT
);
CREATE TABLE IF NOT EXISTS released (name TEXT PRIMARY KEY, patch TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gold (name TEXT PRIMARY KEY, status TEXT NOT NULL, patch TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS upgrade_ships (id INTEGER PRIMARY KEY, name TEXT NOT NULL, msrp INTEGER);
CREATE TABLE IF NOT EXISTS upgrade_skus (
  sku INTEGER PRIMARY KEY, ref INTEGER NOT NULL, name TEXT NOT NULL, title TEXT NOT NULL, price INTEGER NOT NULL,
  msrp INTEGER, listed INTEGER NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cargo (
  key TEXT PRIMARY KEY, name TEXT NOT NULL, names TEXT NOT NULL, scu REAL, extra REAL, boxes TEXT NOT NULL, viewer TEXT
);
"""


def connect(path, check_same_thread=True):
    db = sqlite3.connect(path, check_same_thread=check_same_thread)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    cat = {r["name"] for r in db.execute("PRAGMA table_info(catalog)")}
    if cat and "mid" not in cat:  # older, smaller ship list: it's rebuilt from RSI on the next check
        db.executescript("DROP TABLE catalog; DELETE FROM state WHERE key='catalog_at';")
    db.executescript(SCHEMA)
    wcols = {r["name"] for r in db.execute("PRAGMA table_info(watches)")}
    if "guild_id" not in wcols:
        db.execute("ALTER TABLE watches ADD COLUMN guild_id TEXT NOT NULL DEFAULT ''")
    if "kind" not in wcols:  # 'name' (part of a ship name), 'above' (amount = cents) or 'from' (ref = upgrade ship id)
        db.executescript("ALTER TABLE watches ADD COLUMN kind TEXT NOT NULL DEFAULT 'name';"
                         "ALTER TABLE watches ADD COLUMN amount INTEGER; ALTER TABLE watches ADD COLUMN ref INTEGER;")
    if "weapons" not in {r["name"] for r in db.execute("PRAGMA table_info(ingame)")}:  # filled on the next refresh
        db.executescript("ALTER TABLE ingame ADD COLUMN weapons TEXT; DELETE FROM state WHERE key='ingame_at';")
    cols = {r["name"] for r in db.execute("PRAGMA table_info(ships)")}
    for col, kind in (("qty", "INTEGER"), ("warbond", "INTEGER"), ("insurance", "TEXT"), ("ship_id", "TEXT"),
                      ("extras", "TEXT")):
        if col not in cols:
            db.execute(f"ALTER TABLE ships ADD COLUMN {col} {kind}")
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
                              level, qty, warbond, insurance, ship_id, extras, listed, misses, first_seen, last_seen,
                              listed_since) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?)""",
                           (sid, f["name"], f["url"], f["image"], f["category"], f["price"], f["list_price"],
                            f["available"], f["limited"], f["level"], f.get("qty"), f.get("warbond"),
                            f.get("insurance"), f.get("ship_id"), f.get("extras", "[]"), now, now, now))
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
