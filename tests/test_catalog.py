import json

from pw import catalog
from pw import commands as cmd
from pw import db as store_db
from pw.post import message
from pw.watcher import check

BODY = """<table><tr><th>YOUR SHIP</th><th>OUR LOANER(S)</th></tr>
<tr><td>600i Explorer and Executive</td><td>Cyclone</td></tr>
<tr><td><strong>Arrastra</strong></td><td>Mole, Arrow</td></tr>
<tr><td>Kraken &amp; Kraken Privateer</td><td>Caterpillar, Buccaneer</td></tr></table>"""


def setup(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    check(db, [{"id": "1", "name": "Carrack", "url": "u", "image": "", "category": "Standalone Ships", "price": 60000,
                "list_price": 60000, "available": True, "limited": False, "level": "high", "qty": 0}], now=1)
    ships = [catalog._ship({"name": n, "production_status": st, "manufacturer": {"name": "M"}, "url": "/x"})
             for n, st in [("Idris-P", "flight-ready"), ("Idris-M", "flight-ready"), ("Arrastra", "in-concept"),
                           ("Kraken", "in-concept"), ("Carrack", "flight-ready")]]
    with db:
        db.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ships)
        db.executemany("INSERT INTO loaners VALUES (?,?,?)",
                       [(s, json.dumps(k), l) for s, k, l in catalog.parse_loaners(BODY)])
    return db


def test_parse_loaners():
    rows = catalog.parse_loaners(BODY)
    assert [r[0] for r in rows] == ["600i Explorer and Executive", "Arrastra", "Kraken & Kraken Privateer"]
    assert rows[0][1] == ["600i explorer", "600i executive"] and rows[2][1] == ["kraken", "kraken privateer"]


def test_autocomplete_knows_ships_not_on_sale(tmp_path):
    db = setup(tmp_path)
    assert cmd.names(db, "idr") == ["Idris-M", "Idris-P"]
    assert cmd.names(db, "")[0] == "Carrack"  # in the store now comes first, and only once


def test_watch_and_store_for_ship_not_on_sale(tmp_path):
    db = setup(tmp_path)
    assert "check the spelling" not in cmd.watch(db, "discord", "u", "idris")
    r = cmd.store(db, "kraken")
    assert "**Kraken**: not in the store" in r and "in concept" in r


def test_info_and_card(tmp_path):
    db = setup(tmp_path)
    assert catalog.info(db, "Arrastra") == {"status": "In concept", "loaners": "Mole, Arrow"}
    assert catalog.info(db, "Kraken Privateer - Warbond")["loaners"] == "Caterpillar, Buccaneer"
    assert catalog.info(db, "Carrack") == {"status": "Flight ready"}
    e = {"kind": "new", "name": "Arrastra", "url": "u", "image": "", "price": 50000, "limited": False, "level": "high"}
    fields = {f["name"]: f["value"] for f in message(e, 1, info=catalog.info(db, "Arrastra"))["embeds"][0]["fields"]}
    assert fields["Status"] == "In concept" and fields["Loaners until it flies"] == "Mole, Arrow"
    flyable = message({**e, "name": "Carrack"}, 1, info=catalog.info(db, "Carrack"))["embeds"][0]["fields"]
    assert "Status" not in {f["name"] for f in flyable}


def test_loose_loaner_names():
    assert catalog._same("g12", "g12r") and catalog._same("genesis starliner", "genesis")
    assert catalog._same("kraken", "kraken privateer") and not catalog._same("arrow", "arrastra")
    assert catalog._covers("G12 Variants") == ["g12"]


def _row(name, status):
    return catalog._ship({"name": name, "production_status": status, "manufacturer": {"name": "M"}, "url": "/x"})


def test_status_and_loaner_changes(tmp_path):
    db = store_db.connect(str(tmp_path / "s.db"))
    assert catalog.apply(db, [_row("Kraken", "in-concept")], [("Kraken", ["kraken"], "Caterpillar")], 1) == []
    events = catalog.apply(db, [_row("Kraken", "flight-ready"), _row("Ironclad", "in-concept")],
                           [("Kraken", ["kraken"], "Caterpillar, Buccaneer")], 2)
    got = {(e["kind"], e["name"], e["was"], e["now"]) for e in events}
    assert got == {("status", "Kraken", "In concept", "Flight ready"), ("status", "Ironclad", "", "In concept"),
                   ("loaners", "Kraken", "Caterpillar", "Caterpillar, Buccaneer")}
    m = message(events[0], 2)
    assert m["embeds"][0]["author"]["name"] in ("Now flight ready", "New ship", "Loaners changed")


def test_big_batches_are_logged_not_posted(tmp_path):
    db = store_db.connect(str(tmp_path / "s.db"))
    catalog.apply(db, [_row("A", "in-concept")], [], 1)
    catalog.apply(db, [_row("A", "in-concept")] + [_row(f"S{i}", "in-concept") for i in range(20)], [], 2)
    posted = {r[0] for r in db.execute("SELECT posted FROM events")}
    assert posted == {'{"discord": "skipped", "fluxer": "skipped"}'}


def test_preorder_label(tmp_path):
    e = {"kind": "new", "name": "Kraken", "url": "u", "image": "", "price": 165000, "limited": True, "level": "high"}
    label = message(e, 1, info={"status": "In concept", "loaners": "Caterpillar"})["embeds"][0]["author"]["name"]
    assert label == "New in store · Pre-order · Limited"
