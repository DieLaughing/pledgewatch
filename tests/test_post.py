import io
import json
import urllib.error

from pw import commands as cmd
from pw import db as store_db
from pw import servers
from pw.post import flush, message, money

IDRIS = {"kind": "new", "id": "9", "name": "Idris-P", "url": "https://x/idris", "image": "https://x/i.jpg",
         "price": 150000, "limited": True, "level": "high"}


def test_money():
    assert money(60000) == "$600" and money(4499) == "$44.99" and money(150000) == "$1,500"


def test_new_limited_pings_role():
    m = message(IDRIS, 1_700_000_000, role="42")
    assert m["content"] == "<@&42>" and m["allowed_mentions"] == {"roles": ["42"], "users": []}
    e = m["embeds"][0]
    assert e["author"]["name"] == "New in store · Limited" and e["title"] == "Idris-P"
    assert e["thumbnail"]["url"] == "https://x/i.jpg"
    assert {"name": "Stock", "value": "Limited, high", "inline": True} in e["fields"]


def test_price_change_does_not_ping():
    m = message({**IDRIS, "kind": "price", "limited": False, "price": 54000, "was": 60000}, 1, role="42")
    assert "content" not in m and m["allowed_mentions"] == {"parse": []}
    assert {"name": "Change", "value": "-10%", "inline": True} in m["embeds"][0]["fields"]


class FakeApp:
    def __init__(self, name, fail=None):
        self.name, self.fail, self.sent = name, fail, []

    def send(self, channel, msg):
        if self.fail:
            raise self.fail
        self.sent.append((channel, msg))
        return {"id": str(len(self.sent))}


def two_servers(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    servers.seed(db, {"DISCORD_TOKEN": "x", "DISCORD_GUILD_ID": "home", "DISCORD_CHANNEL_ID": "c-home",
                      "FLUXER_TOKEN": "y", "FLUXER_GUILD_ID": "fx", "FLUXER_CHANNEL_ID": "c-fx"})
    servers.save(db, "discord", "other", "c-other", "r-other")
    with db:
        db.execute("UPDATE servers SET added=0")
    return db


def test_flush_posts_to_every_server_and_retries_only_failures(tmp_path):
    db = two_servers(tmp_path)
    store_db.save(db, {}, [IDRIS], now=1000)
    discord, fluxer = FakeApp("discord"), FakeApp("fluxer", fail=urllib.error.URLError("down"))
    flush(db, [discord, fluxer], now=1010)
    assert sorted(c for c, _ in discord.sent) == ["c-home", "c-other"]
    other = [m for c, m in discord.sent if c == "c-other"][0]
    assert other["content"] == "<@&r-other>"  # each server pings its own role
    fluxer.fail = None
    flush(db, [discord, fluxer], now=1020)
    assert len(discord.sent) == 2 and [c for c, _ in fluxer.sent] == ["c-fx"]


def test_server_that_blocks_the_bot_is_switched_off(tmp_path):
    db = two_servers(tmp_path)
    store_db.save(db, {}, [IDRIS], now=1000)
    forbidden = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b'{"message": "Missing Access"}'))

    class Picky(FakeApp):
        def send(self, channel, msg):
            if channel == "c-other":
                raise forbidden
            return super().send(channel, msg)

    flush(db, [Picky("discord")], now=1010)
    row = servers.get(db, "discord", "other")
    assert row["active"] == 0 and "403" in row["note"]
    assert servers.get(db, "discord", "home")["active"] == 1


def test_new_server_does_not_get_old_alerts(tmp_path):
    db = two_servers(tmp_path)
    store_db.save(db, {}, [IDRIS], now=1000)
    with db:
        db.execute("UPDATE servers SET added=2000 WHERE guild_id='other'")
    app = FakeApp("discord")
    flush(db, [app], now=2010)
    assert [c for c, _ in app.sent] == ["c-home"]  # "other" was set up after the event


def test_watch_pings_in_the_server_it_was_made_in(tmp_path):
    db = two_servers(tmp_path)
    cmd.watch(db, "discord", "u1", "idris", guild="other")
    cmd.watch(db, "discord", "u2", "idris", guild="home")
    store_db.save(db, {}, [IDRIS], now=1000)
    app = FakeApp("discord")
    flush(db, [app], now=1010)
    sent = dict(app.sent)
    assert "<@u1>" in sent["c-other"]["content"] and "<@u2>" not in sent["c-other"]["content"]
    assert "<@u2>" in sent["c-home"]["content"]


def test_flush_skips_stale_events(tmp_path):
    db = two_servers(tmp_path)
    store_db.save(db, {}, [IDRIS], now=1000)
    app = FakeApp("discord")
    flush(db, [app], now=1000 + 7200)
    assert app.sent == []


def test_leaving_a_server_forgets_it(tmp_path):
    db = two_servers(tmp_path)
    cmd.watch(db, "discord", "u1", "idris", guild="other")
    servers.forget(db, "discord", "other")
    assert servers.get(db, "discord", "other") is None and cmd.watching(db, "discord", "u1").startswith("You're not")
