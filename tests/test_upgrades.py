from pw import commands as cmd
from pw import db as store_db
from pw import upgrades
from pw.bots import fluxer_reply
from pw.post import flush, message
from tests.test_post import FakeApp, two_servers

M2, CARRACK, POLARIS = 163, 62, 116


def ships(*extra):
    base = [
        {"id": M2, "name": "M2 Hercules Starlifter", "msrp": 52000, "image": "", "skus": []},
        {"id": CARRACK, "name": "Carrack", "msrp": 60000, "image": "",
         "skus": [{"id": 1, "title": "Standard Edition", "price": 60000}]},
        {"id": POLARIS, "name": "Polaris", "msrp": 97500, "image": "",
         "skus": [{"id": 2, "title": "Standard Edition", "price": 97500},
                  {"id": 3, "title": "Imperator Subscribers Edition", "price": 90000}]},
    ]
    for ref, sku in extra:
        next(s for s in base if s["id"] == ref)["skus"].append(sku)
    return base


def test_first_look_is_quiet_and_subscriber_editions_are_skipped(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    assert upgrades.check(db, ships(), now=1) == []
    assert [r[0] for r in db.execute("SELECT sku FROM upgrade_skus ORDER BY sku")] == [1, 2]


def test_new_warbond_upgrade_pings_matching_price_watches(tmp_path):
    db = two_servers(tmp_path)
    upgrades.check(db, ships(), now=1)
    cmd.watch(db, "discord", "above", "above:$520", guild="home")
    cmd.watch(db, "discord", "rich", "above:1000", guild="home")
    cmd.watch(db, "discord", "m2", "from:m2 hercules", guild="home")
    cmd.watch(db, "discord", "name", "carrack", guild="home")
    warbond = {"id": 4, "title": "Warbond Edition", "price": 57000}
    events = upgrades.check(db, ships((CARRACK, warbond)), costs={M2: {1: 8000}}, now=2)
    assert [(e["name"], e["title"], e["costs"]) for e in events] == [("Carrack", "Warbond Edition", {})]
    # The M2 can't take this warbond edition (RSI didn't list it from the M2), so only above:520 is pinged.
    assert cmd.watchers(db, "discord", events[0], "home") == ["above"]

    events = upgrades.check(db, ships((CARRACK, {**warbond, "price": 56000})), costs={M2: {1: 8000, 4: 4000}}, now=3)
    assert events[0]["was"] == 57000 and events[0]["costs"] == {str(M2): 4000}
    assert cmd.watchers(db, "discord", events[0], "home") == ["above", "m2"]

    discord = FakeApp("discord")
    flush(db, [discord], now=4)
    assert [c for c, _ in discord.sent] == ["c-home", "c-home"]  # not c-other: nobody there asked
    m = discord.sent[1][1]
    assert m["embeds"][0]["author"]["name"] == "Warbond upgrade price drop"
    assert {"name": "You pay", "value": "From M2 Hercules Starlifter: **$40**", "inline": False} \
        in m["embeds"][0]["fields"]
    assert m["allowed_mentions"] == {"roles": [], "users": ["above", "m2"]}


def test_price_watches_on_ship_store_events():
    w = {"kind": "above", "amount": 52000, "ref": None, "query": "above:$520"}
    assert cmd._wants(w, {"kind": "new", "name": "Polaris", "price": 97500})
    assert not cmd._wants(w, {"kind": "new", "name": "Gladius", "price": 9000})
    assert not cmd._wants(w, {"kind": "price", "name": "Polaris", "price": 99000, "was": 97500})
    assert not cmd._wants(w, {"kind": "sold_out", "name": "Polaris", "price": 97500})


def test_watch_parsing_and_unwatch(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    assert "haven't read the upgrade store" in cmd.watch(db, "discord", "u", "from:M2")
    upgrades.check(db, ships(), now=1)
    assert "dollar amount" in cmd.watch(db, "discord", "u", "above:lots")
    assert "Did you mean **Carrack**" in cmd.watch(db, "discord", "u", "from:carack")
    assert "Watching **above:$1200**" in cmd.watch(db, "discord", "u", "over $1,200")
    reply = cmd.watch(db, "discord", "u", "from:M2")
    assert "Watching **from:M2 Hercules Starlifter** ($520)" in reply and "Carrack (Standard, $600)" in reply
    assert "already watching" in cmd.watch(db, "discord", "u", "from: m2 hercules starlifter")
    assert "upgrades your ship can take" in cmd.watching(db, "discord", "u")
    assert "Stopped watching **above:$1200**" in cmd.unwatch(db, "discord", "u", "above:$1200")
    assert "Stopped watching **from:M2 Hercules Starlifter**" in cmd.unwatch(db, "discord", "u", "from:M2")
    assert "Watching **above:$520**" in fluxer_reply(db, "!watch above:520", "u")


def test_upgrade_message_without_owner_ship():
    e = {"kind": "upgrade", "name": "Carrack", "title": "Warbond Edition", "price": 57000, "msrp": 60000,
         "url": upgrades.PAGE, "image": ""}
    fields = message(e, 0, users=["u"])["embeds"][0]["fields"]
    assert {"name": "Standard", "value": "$600 (saves $30)", "inline": True} in fields


def test_site_shows_upgrades_and_values(tmp_path):
    from pw import site
    db = store_db.connect(str(tmp_path / "t.db"))
    with db:
        db.execute("INSERT INTO catalog (name, key) VALUES ('Carrack', 'carrack'), "
                   "('M2 Hercules Starlifter', 'm2 hercules starlifter')")
    upgrades.check(db, ships((CARRACK, {"id": 4, "title": "BIS Warbond Edition", "price": 56000})), now=1)
    by = {s["name"]: s for s in site.build(db)["ships"]}
    assert by["Carrack"]["ccu"] == {"ref": CARRACK, "value": 60000}
    assert [(u["label"], u["price"]) for u in by["Carrack"]["upgrades"]] == [("BIS Warbond", 56000), ("Standard", 60000)]
    assert by["M2 Hercules Starlifter"]["ccu"]["value"] == 52000 and "upgrades" not in by["M2 Hercules Starlifter"]
    assert site.upgrade_label("Aegis Reclaimer Best in Show Edition Upgrade") == "Best in Show"


def test_map_paths_keeps_ships_that_failed_and_drops_bad_runs(tmp_path, monkeypatch):
    from pw import site
    monkeypatch.setattr(upgrades, "MAP_PAUSE", 0)
    db = store_db.connect(str(tmp_path / "t.db"))
    upgrades.check(db, ships((CARRACK, {"id": 4, "title": "Warbond Edition", "price": 57000})), now=1)
    assert upgrades.map_paths(db, {M2: {1: 8000, 4: 5000}, CARRACK: {2: 37500}, POLARIS: {}}.get, now=2) == 3

    def flaky(ref):
        if ref == M2:
            raise upgrades.StoreError("timeout")
        return {CARRACK: {2: 37000}, POLARIS: {}}[ref]
    monkeypatch.setattr(upgrades, "MAP_MIN_SHARE", 0.5)
    assert upgrades.map_paths(db, flaky, now=3) == 2
    p = site.plan(db)
    assert p["at"] == 3 and p["paths"] == {str(M2): [[4, 5000], [1, 8000]], str(CARRACK): [[2, 37000]]}
    assert p["skus"][4] == [CARRACK, "Warbond", 57000] and [M2, "M2 Hercules Starlifter", 52000] in p["ships"]

    monkeypatch.setattr(upgrades, "MAP_MIN_SHARE", 0.9)
    assert upgrades.map_paths(db, flaky, now=4) == 0  # 2 of 3 answered: the map stays as it was
    assert site.plan(db)["at"] == 3

    # An upgrade that has left the store since the map run isn't offered.
    upgrades.check(db, ships(), now=5)
    assert site.plan(db)["paths"][str(M2)] == [[1, 8000]]
