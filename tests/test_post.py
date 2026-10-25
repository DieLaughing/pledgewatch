import json
import urllib.error

from pw import db as store_db
from pw.post import flush, message, money

IDRIS = {"kind": "new", "id": "9", "name": "Idris-P", "url": "https://x/idris", "image": "https://x/i.jpg",
         "price": 150000, "limited": True, "level": "high"}


def test_money():
    assert money(60000) == "$600" and money(4499) == "$44.99" and money(150000) == "$1,500"


def test_new_limited_pings_role():
    m = message(IDRIS, 1_700_000_000, role="42")
    assert m["content"] == "<@&42>" and m["allowed_mentions"] == {"roles": ["42"]}
    e = m["embeds"][0]
    assert e["author"]["name"] == "New in store · Limited" and e["title"] == "Idris-P"
    assert e["thumbnail"]["url"] == "https://x/i.jpg"
    assert {"name": "Stock", "value": "Limited, high", "inline": True} in e["fields"]


def test_price_change_does_not_ping():
    m = message({**IDRIS, "kind": "price", "limited": False, "price": 54000, "was": 60000}, 1, role="42")
    assert "content" not in m and m["allowed_mentions"] == {"parse": []}
    assert {"name": "Change", "value": "-10%", "inline": True} in m["embeds"][0]["fields"]


class FakeApp:
    def __init__(self, name, fail=False):
        self.name, self.role, self.fail, self.sent = name, None, fail, []

    def send(self, msg):
        if self.fail:
            raise urllib.error.URLError("down")
        self.sent.append(msg)
        return {"id": str(len(self.sent))}


def test_flush_retries_only_the_app_that_failed(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    store_db.save(db, {}, [IDRIS], now=1000)
    discord, fluxer = FakeApp("discord"), FakeApp("fluxer", fail=True)
    flush(db, [discord, fluxer], now=1010)
    assert len(discord.sent) == 1 and json.loads(db.execute("SELECT posted FROM events").fetchone()[0]) == {"discord": "1"}
    fluxer.fail = False
    flush(db, [discord, fluxer], now=1020)
    assert len(discord.sent) == 1 and len(fluxer.sent) == 1


def test_flush_skips_stale_events(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    store_db.save(db, {}, [IDRIS], now=1000)
    app = FakeApp("discord")
    flush(db, [app], now=1000 + 7200)
    assert app.sent == []
