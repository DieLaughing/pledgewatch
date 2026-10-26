"""Post logged changes to the Discord and Fluxer channels.

Both apps take the same message format (content + embeds + allowed_mentions) at POST /channels/{id}/messages, so one
formatter serves both. Every event remembers which apps it reached, so a failed post is retried on the next check.
"""
import datetime
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("pledgewatch")

# Don't post alerts older than this (e.g. after the bot was down for a while); they'd only be noise.
MAX_AGE = 3600

# kind: (label, colour, ping the role?)
KINDS = {
    "new":        ("New in store",          0x3ECF8E, True),
    "back":       ("Back in store",         0x3ECF8E, True),
    "restock":    ("Back in stock",         0x3ECF8E, True),
    "low":        ("Stock running low",     0xF0B44A, False),
    "sold_out":   ("Sold out",              0xEF5F6B, False),
    "gone":       ("Left the store",        0xEF5F6B, False),
    "price":      ("Price change",          0x8F8CF2, False),
    "status":     ("Flight status changed", 0x5B8DEF, False),
    "loaners":    ("Loaners changed",       0x5B8DEF, False),
    "upgrade":    ("Upgrade in store",      0x3ECF8E, False),
    "store_down": ("Can't read the store",  0x8B97A8, False),
    "store_ok":   ("Store readable again",  0x8B97A8, False),
}


class App:
    """Sends messages for one chat app. Which channels it posts to comes from the servers table."""

    def __init__(self, name, api, token):
        self.name, self.api, self.token = name, api, token

    def send(self, channel, message, retry=True):
        req = urllib.request.Request(f"{self.api}/channels/{channel}/messages", data=json.dumps(message).encode(),
                                     headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json",
                                              "User-Agent": "PledgeWatch (https://pledgewatch.inpints.com)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and retry:  # slow down: wait as long as the app asks, then try once more
                wait = float(json.loads(e.read() or b"{}").get("retry_after", 2))
                time.sleep(min(wait, 30))
                return self.send(channel, message, retry=False)
            raise


def apps_from_env(env=os.environ):
    apps = []
    if env.get("DISCORD_TOKEN"):
        apps.append(App("discord", "https://discord.com/api/v10", env["DISCORD_TOKEN"]))
    if env.get("FLUXER_TOKEN"):
        apps.append(App("fluxer", env["FLUXER_API"].rstrip("/") + "/api/v1", env["FLUXER_TOKEN"]))
    return apps


def money(cents):
    if cents is None:
        return "?"
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def ago(ts, now):
    days = (now - ts) // 86400
    if days >= 60:
        return f"{days // 30} months ago"
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return "earlier today"


def message(e, ts, role=None, users=(), info=None, froms=()):
    """Build the message for one event. `users` are people watching this ship, pinged by name. `info` is the
    ship's status and loaners from the catalog, shown when it isn't flight ready. `froms` are (ship, cost) pairs for
    an upgrade: what it costs from the ships the pinged people own."""
    label, colour, ping = KINDS[e["kind"]]
    if e["kind"] == "upgrade":
        return _upgrade_message(e, ts, label, colour, users, froms)
    if e["kind"] in ("store_down", "store_ok"):
        text = (f"The RSI store has failed {e.get('fails', 3)} checks in a row. Alerts are paused until it answers "
                f"again.\n-# {e.get('reason', '')}") if e["kind"] == "store_down" else "Alerts are back on."
        return {"embeds": [{"title": label, "description": text, "color": colour, "timestamp": _iso(ts)}],
                "allowed_mentions": {"parse": []}}

    if e["kind"] in ("status", "loaners"):
        return _matrix_message(e, ts, label, colour, users)
    info = info or {}
    if e["kind"] in ("new", "back") and info.get("status") and info["status"] != "Flight ready":
        label += " · Pre-order"
    if e.get("limited") and e["kind"] in ("new", "back", "restock", "low"):
        label += " · Limited"
    fields = [{"name": "Price", "value": money(e["price"]), "inline": True}]
    if e["kind"] == "price":
        change = (e["price"] - e["was"]) / e["was"] * 100 if e.get("was") else 0
        fields += [{"name": "Was", "value": money(e.get("was")), "inline": True},
                   {"name": "Change", "value": f"{change:+.0f}%", "inline": True}]
    elif e["kind"] == "low":
        fields.append({"name": "Stock", "value": f"{e['level'].title()} (was {e.get('was', '?')})", "inline": True})
    elif e["kind"] in ("new", "back", "restock"):
        fields.append({"name": "Stock", "value": f"Limited, {e['level'] or '?'}" if e.get("limited") else "Unlimited",
                       "inline": True})
    if e["kind"] == "back" and e.get("last_seen"):
        fields.append({"name": "Last seen", "value": ago(e["last_seen"], ts), "inline": True})

    if info.get("status") and info["status"] != "Flight ready":
        fields.append({"name": "Status", "value": info["status"], "inline": True})
    if info.get("loaners") and info.get("status") != "Flight ready":
        fields.append({"name": "Loaners until it flies", "value": info["loaners"], "inline": False})

    embed = {"author": {"name": label}, "title": e["name"], "url": e["url"], "color": colour, "fields": fields,
             "footer": {"text": "Public store: what anyone can buy, logged out · USD before tax"}, "timestamp": _iso(ts)}
    if e.get("image"):
        embed["thumbnail"] = {"url": e["image"]}
    msg = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    roles = [role] if ping and role else []
    if roles or users:
        msg["content"] = " ".join([f"<@&{r}>" for r in roles] + [f"<@{u}>" for u in users])
        msg["allowed_mentions"] = {"roles": roles, "users": list(users)}
    return msg


def _matrix_message(e, ts, label, colour, users):
    """A ship's flight status or loaners changed in RSI's Ship Matrix / Loaner Ship Matrix."""
    if e["kind"] == "status":
        label = "Now flight ready" if e["now"] == "Flight ready" else ("New ship" if not e["was"] else label)
        fields = [{"name": "Status", "value": f"{e['was']} → {e['now']}" if e["was"] else e["now"], "inline": True}]
        source = "RSI Ship Matrix"
    else:
        fields = [{"name": "Loaners now", "value": e["now"] or "None listed (likely flight ready)", "inline": False}]
        if e["was"]:
            fields.append({"name": "Was", "value": e["was"], "inline": False})
        source = "RSI Loaner Ship Matrix"
    embed = {"author": {"name": label}, "title": e["name"], "color": colour, "fields": fields,
             "footer": {"text": source}, "timestamp": _iso(ts)}
    if e.get("url"):
        embed["url"] = e["url"]
    msg = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if users:
        msg["content"] = " ".join(f"<@{u}>" for u in users)
        msg["allowed_mentions"] = {"roles": [], "users": list(users)}
    return msg


def _upgrade_message(e, ts, label, colour, users, froms):
    """An upgrade (CCU) edition came into the upgrade store, came back, or got cheaper. Only posted to ping watchers."""
    warbond = "warbond" in e["title"].lower()
    if e.get("was"):
        label = "Upgrade price drop"
    elif e.get("back"):
        label = "Upgrade back in store"
    if warbond:
        label = "Warbond " + label[0].lower() + label[1:]
    fields = [{"name": "Edition", "value": e["title"], "inline": True},
              {"name": "Upgrade value", "value": money(e["price"]), "inline": True}]
    if e.get("was"):
        fields.append({"name": "Was", "value": money(e["was"]), "inline": True})
    elif e.get("msrp") and e["msrp"] > e["price"]:
        fields.append({"name": "Standard", "value": f"{money(e['msrp'])} (saves {money(e['msrp'] - e['price'])})",
                       "inline": True})
    if froms:
        fields.append({"name": "You pay", "value": "\n".join(f"From {n}: **{money(c)}**" for n, c in froms),
                       "inline": False})
    note = "Warbond: new money only, no store credit · " if warbond else ""
    embed = {"author": {"name": label}, "title": e["name"], "url": e["url"], "color": colour, "fields": fields,
             "footer": {"text": note + "You pay the upgrade value minus your ship's · Buy from your RSI hangar (Ship Upgrade) · USD"},
             "timestamp": _iso(ts)}
    if e.get("image"):
        embed["thumbnail"] = {"url": e["image"]}
    msg = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if users:
        msg["content"] = " ".join(f"<@{u}>" for u in users)
        msg["allowed_mentions"] = {"roles": [], "users": list(users)}
    return msg


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat()


def flush(db, apps, now=None):
    """Post every event to every active server that hasn't had it yet. Safe to call after each check.
    A server that has blocked the bot (no access to its channel, channel deleted) is switched off, not retried."""
    from . import servers
    from .catalog import info
    from .commands import from_costs, watchers
    now = int(now or time.time())
    by_name = {a.name: a for a in apps}
    dests = [d for d in servers.active(db) if d["platform"] in by_name]
    rows = db.execute("SELECT id, ts, data, posted FROM events WHERE ts >= ? ORDER BY id", (now - MAX_AGE,)).fetchall()
    off = set()
    for row in rows:
        posted = json.loads(row["posted"])
        e = json.loads(row["data"])
        ship = info(db, e.get("name", ""))
        for d in dests:
            key = f"{d['platform']}:{d['guild_id']}"
            if key in posted or key in off or d["added"] > row["ts"] or d["platform"] in posted:
                continue  # done, switched off this round, set up after the event, or posted before per-server keys
            try:
                users = watchers(db, d["platform"], e, d["guild_id"])
                if e["kind"] == "upgrade":  # upgrades only go to servers where someone asked for them
                    if not users:
                        posted[key] = False
                        continue
                    msg = message(e, row["ts"], users=users, froms=from_costs(db, d["platform"], e, d["guild_id"], users))
                else:
                    msg = message(e, row["ts"], d["role_id"] or None, users, ship)
                posted[key] = by_name[d["platform"]].send(d["channel_id"], msg).get("id", True)
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:200]
                if err.code in (403, 404):
                    servers.switch_off(db, d["platform"], d["guild_id"], f"HTTP {err.code}: {detail}")
                    off.add(key)
                    log.warning("switched off %s: can't post to its channel (%s)", key, err.code)
                else:
                    log.warning("couldn't post %s to %s: %s %s", e["kind"], key, err, detail)
            except (urllib.error.URLError, TimeoutError, ValueError) as err:
                log.warning("couldn't post %s to %s: %s", e["kind"], key, err)
        with db:
            db.execute("UPDATE events SET posted=? WHERE id=?", (json.dumps(posted), row["id"]))
