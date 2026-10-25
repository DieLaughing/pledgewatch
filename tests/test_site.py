from pw import catalog
from pw import db as store_db
from pw.site import build, edition
from pw.watcher import check


def item(sid, name, price, url=None):
    return {"id": sid, "name": name, "url": url or f"https://x/{name.replace(' ', '-')}", "image": "", "qty": 0,
            "category": "Standalone Ships", "price": price, "list_price": price, "available": True,
            "limited": False, "level": "high"}


def test_edition_labels():
    assert edition("Constellation Mk V Centaurus", "/pledge/x/Constellation-Mk-V-Centaurus-Warbond") == "Warbond"
    assert edition("Constellation Mk IV Taurus - 10 Year", "/x") == "10 Year"
    assert edition("Carrack", "/pledge/x/Carrack") == "Standard"


def test_build_groups_editions_under_one_ship(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    rows = [catalog._ship({"name": n, "production_status": "flight-ready", "manufacturer": {"name": "M", "code": "M"},
                           "size": "medium", "url": "/x"}) for n in ["Constellation Mk V Centaurus", "PTV", "Polaris"]]
    with db:
        db.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    check(db, [item("1", "Constellation Mk V Centaurus", 27500, "/x/Constellation-Mk-V-Centaurus-Warbond"),
               item("2", "Constellation Mk V Centaurus - 10 Year", 30000), item("3", "PTV Buggy", 1500)], now=100)
    ships = {s["name"]: s for s in build(db, now=200)["ships"]}
    assert set(ships) == {"Constellation Mk V Centaurus", "PTV", "Polaris"}
    assert [(e["label"], e["price"]) for e in ships["Constellation Mk V Centaurus"]["editions"]] == \
        [("Warbond", 27500), ("10 Year", 30000)]
    assert ships["PTV"]["inStore"] and not ships["Polaris"]["inStore"] and ships["Polaris"]["size"] == "Medium"


def test_ship_id_beats_name_and_insurance_flows_through(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    rows = [catalog._ship({"id": 7, "name": "Constellation Centaurus", "production_status": "flight-ready",
                           "manufacturer": {"name": "RSI"}, "url": "/x"})]
    with db:
        db.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    wb = {**item("1", "Constellation Mk V Centaurus", 27500), "warbond": True, "insurance": "Lifetime",
          "ship_id": "7", "extras": ["Skylark - Convergence Paint", "Revel & York Hangar"]}
    check(db, [wb], now=100)
    ship = [s for s in build(db, now=200)["ships"] if s["name"] == "Constellation Centaurus"][0]
    e = ship["editions"][0]
    assert (e["label"], e["insurance"], e["paints"], e["includes"]) == ("Warbond", "Lifetime", 1,
                                                                         ["Skylark - Convergence Paint"])
