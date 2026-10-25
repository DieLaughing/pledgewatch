"""What /watch, /unwatch, /watching and /store do. Shared by both apps; each returns the reply text."""
import re
import time

from .post import ago, money

MAX_WATCHES = 20
ACCESS_NOTE = "-# I only see the public store, the one you see when logged out. Concierge and subscriber early access isn't visible to me."

# Changes that ping the people watching a ship.
WATCH_KINDS = {"new", "back", "restock", "low", "price"}


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def matches(query, name):
    return norm(query) in norm(name)


def watch(db, platform, user, query, now=None):
    q = norm(query)
    if len(q) < 2:
        return "Give me at least two letters of a ship name, like `Idris` or `Carrack`."
    if len(q) > 40:
        return "That's a long name. Try a shorter part of it, like `Polaris`."
    mine = _mine(db, platform, user)
    if q in mine:
        return f"You're already watching **{q}**. " + _now_line(db, q)
    if len(mine) >= MAX_WATCHES:
        return f"You're watching {MAX_WATCHES} ships, which is the limit. Remove one with `unwatch` first."
    with db:
        db.execute("INSERT INTO watches (platform, user_id, query, created) VALUES (?,?,?,?)",
                   (platform, user, q, int(now or time.time())))
    reply = (f"Watching **{q}**. I'll ping you when a ship matching it comes into the public store, restocks, "
             f"runs low or changes price.\n" + _now_line(db, q))
    if not _ships(db, q):
        reply += ("\nI haven't seen a ship with that name yet, so check the spelling. I match any ship whose name "
                  "contains it.")
    return reply


def unwatch(db, platform, user, query):
    q = norm(query)
    with db:
        if q == "all":
            n = db.execute("DELETE FROM watches WHERE platform=? AND user_id=?", (platform, user)).rowcount
            return f"Stopped watching all {n} ship(s)." if n else "You weren't watching anything."
        n = db.execute("DELETE FROM watches WHERE platform=? AND user_id=? AND query=?", (platform, user, q)).rowcount
    if n:
        return f"Stopped watching **{q}**."
    mine = _mine(db, platform, user)
    return f"You weren't watching **{q}**." + (f" You're watching: {', '.join(mine)}." if mine else "")


def watching(db, platform, user):
    mine = _mine(db, platform, user)
    if not mine:
        return "You're not watching any ships. Add one with `watch`, like `watch Idris`."
    lines = [f"You're watching {len(mine)} ship(s):"]
    for q in mine:
        lines.append(f"- **{q}**: " + _now_line(db, q, short=True))
    return "\n".join(lines)


def store(db, query=None, now=None):
    now = int(now or time.time())
    if not query or not norm(query):
        rows = db.execute("SELECT COUNT(*), SUM(limited) FROM ships WHERE listed=1").fetchone()
        return f"{rows[0]} ships are in the public store right now, {rows[1] or 0} of them limited.\n{ACCESS_NOTE}"
    q = norm(query)
    ships = _ships(db, q)
    if not ships:
        since = db.execute("SELECT MIN(first_seen) FROM ships").fetchone()[0] or now
        return (f"Nothing matching **{q}** is in the public store, and I haven't seen it since I started watching "
                f"{ago(since, now)}.\n{ACCESS_NOTE}")
    lines = []
    for s in ships[:8]:
        if s["listed"]:
            state = "sold out" if not s["available"] else ("limited, " + (s["level"] or "?") if s["limited"] else "in store")
            lines.append(f"- **{s['name']}**: {money(s['price'])}, {state}")
        else:
            lines.append(f"- **{s['name']}**: not in the store, last seen {ago(s['last_seen'], now)}")
    if len(ships) > 8:
        lines.append(f"- and {len(ships) - 8} more. Try a longer name.")
    return "\n".join(lines) + "\n" + ACCESS_NOTE


def names(db, current, limit=25):
    """Ship names for autocomplete, in-store ships first."""
    q = norm(current)
    rows = db.execute("SELECT name FROM ships ORDER BY listed DESC, name").fetchall()
    return [r[0] for r in rows if q in norm(r[0])][:limit]


def watchers(db, platform, event):
    """User ids on `platform` who should be pinged for this event."""
    if event["kind"] not in WATCH_KINDS or not event.get("name"):
        return []
    rows = db.execute("SELECT user_id, query FROM watches WHERE platform=?", (platform,)).fetchall()
    return sorted({r[0] for r in rows if matches(r[1], event["name"])})


HELP = """**Pledge Watch** posts changes in the public RSI pledge store: ships coming in, selling out, changing price or leaving.
`{p}watch <ship>`: ping me about a ship (part of the name is fine, like `Idris`)
`{p}unwatch <ship>` or `{p}unwatch all`: stop
`{p}watching`: what I'm watching for you
`{p}store [ship]`: is it in the store right now?
""" + ACCESS_NOTE


def _mine(db, platform, user):
    return [r[0] for r in db.execute("SELECT query FROM watches WHERE platform=? AND user_id=? ORDER BY created",
                                     (platform, user))]


def _ships(db, q):
    rows = db.execute("SELECT * FROM ships ORDER BY listed DESC, price DESC").fetchall()
    return [r for r in rows if q in norm(r["name"])]


def _now_line(db, q, short=False):
    ships = _ships(db, q)
    listed = [s for s in ships if s["listed"]]
    if listed:
        names_ = ", ".join(f"{s['name']} ({money(s['price'])})" for s in listed[:3])
        more = f" and {len(listed) - 3} more" if len(listed) > 3 else ""
        return ("in store now: " if short else "Right now it's in the store: ") + names_ + more
    return "not in the store right now" if short else "Right now it's not in the public store."
