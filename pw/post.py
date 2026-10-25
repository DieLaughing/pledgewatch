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
    "store_down": ("Can't read the store",  0x8B97A8, False),
    "store_ok":   ("Store readable again",  0x8B97A8, False),
}


class App:
    def __init__(self, name, api, token, channel, role):
        self.name, self.api, self.token, self.channel, self.role = name, api, token, channel, role

    def send(self, message):
        req = urllib.request.Request(f"{self.api}/channels/{self.channel}/messages", data=json.dumps(message).encode(),
                                     headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json",
                                              "User-Agent": "PledgeWatch (https://github.com/DieLaughing/pledgewatch)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)


def apps_from_env(env=os.environ):
    apps = []
    if env.get("DISCORD_TOKEN"):
        apps.append(App("discord", "https://discord.com/api/v10", env["DISCORD_TOKEN"], env["DISCORD_CHANNEL_ID"],
                        env.get("DISCORD_ROLE_ID")))
    if env.get("FLUXER_TOKEN"):
        apps.append(App("fluxer", env["FLUXER_API"].rstrip("/") + "/api/v1", env["FLUXER_TOKEN"],
                        env["FLUXER_CHANNEL_ID"], env.get("FLUXER_ROLE_ID")))
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


def message(e, ts, role=None):
    """Build the message for one event."""
    label, colour, ping = KINDS[e["kind"]]
    if e["kind"] in ("store_down", "store_ok"):
        text = (f"The RSI store has failed {e.get('fails', 3)} checks in a row. Alerts are paused until it answers "
                f"again.\n-# {e.get('reason', '')}") if e["kind"] == "store_down" else "Alerts are back on."
        return {"embeds": [{"title": label, "description": text, "color": colour, "timestamp": _iso(ts)}],
                "allowed_mentions": {"parse": []}}

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

    embed = {"author": {"name": label}, "title": e["name"], "url": e["url"], "color": colour, "fields": fields,
             "footer": {"text": "RSI pledge store · USD before tax"}, "timestamp": _iso(ts)}
    if e.get("image"):
        embed["thumbnail"] = {"url": e["image"]}
    msg = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if ping and role:
        msg["content"] = f"<@&{role}>"
        msg["allowed_mentions"] = {"roles": [role]}
    return msg


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat()


def flush(db, apps, now=None):
    """Post every event that hasn't reached every app yet. Safe to call after each check."""
    now = int(now or time.time())
    rows = db.execute("SELECT id, ts, data, posted FROM events WHERE ts >= ? ORDER BY id", (now - MAX_AGE,)).fetchall()
    for row in rows:
        posted = json.loads(row["posted"])
        e = json.loads(row["data"])
        for app in apps:
            if app.name in posted:
                continue
            try:
                posted[app.name] = app.send(message(e, row["ts"], app.role)).get("id", True)
            except (urllib.error.URLError, TimeoutError, ValueError) as err:
                detail = err.read().decode(errors="replace")[:200] if isinstance(err, urllib.error.HTTPError) else ""
                log.warning("couldn't post %s to %s: %s %s", e["kind"], app.name, err, detail)
        with db:
            db.execute("UPDATE events SET posted=? WHERE id=?", (json.dumps(posted), row["id"]))
