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


def test_whats_new_page_and_newest():
    from pw import whatsnew
    dates = [d for d, _ in whatsnew.ENTRIES]
    assert dates == sorted(dates, reverse=True) and whatsnew.NEWEST.startswith(dates[0] + "#") and whatsnew.NEWEST > dates[0]
    page = whatsnew.page()
    assert "<code>/watch above:520</code>" in page and "October 26, 2026" in page


def test_plan_page_carries_its_map_and_title(tmp_path):
    import os
    from pw.site import PLAN_DESCRIPTION, Site
    dist = tmp_path / "dist"
    os.makedirs(dist)
    page = open(os.path.join(os.path.dirname(__file__), "..", "web", "index.html")).read()
    (dist / "index.html").write_text(page)
    site = Site(str(tmp_path / "t.db"), str(dist))
    site.refresh()
    html = site.plan_page.decode()
    assert '<script id="plan" type="application/json">{"at":null' in html and 'id="data"' not in html
    assert "<title>Upgrade planner · Pledge Watch</title>" in html and PLAN_DESCRIPTION in html


def test_modules_on_sale_attach_to_their_ship_with_fitted_cargo(tmp_path):
    from pw.site import module_of
    from pw.store import is_module
    db = store_db.connect(str(tmp_path / "t.db"))
    rows = [catalog._ship({"id": i, "name": n, "production_status": "flight-ready", "manufacturer": {"name": "RSI"},
                           "url": "/x"}) for i, n in ((244, "Galaxy"), (1, "Aurora Mk II"), (2, "Aurora"))]
    with db:
        db.executemany("INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO cargo VALUES (?,?,?,?,?,?,?)", [
            ("galaxy", "Galaxy", '["galaxy"]', 64, None, "[[0,0,0,2,4,4]]", "v1"),
            ("galaxy cargo", "Galaxy [Cargo]", '["galaxy cargo"]', 720, None, "[[0,0,0,6,12,2]]", "v2"),
            ("galaxy medical", "Galaxy [Medical]", '["galaxy medical"]', 68, None, "[[0,0,0,2,4,4]]", "v3")])
    pack = {**item("5", "Galaxy Hospital - 10 Year", 44500), "warbond": True, "ship_id": "244",
            "extras": ["Galaxy - Med Bay Module", "VFG Industrial Hangar"]}
    check(db, [{**item("4", "Galaxy - 10 Year", 36000), "warbond": True, "ship_id": "244"}, pack], now=100)
    mod = {**item("9", "Galaxy - Cargo Module - 10 Year", 7000), "category": "Add-Ons", "warbond": False}
    store_db.save_modules(db, [mod, {**item("8", "Aurora Mk II Cargo Module", 1000), "category": "Add-Ons"}])

    ships = {s["name"]: s for s in build(db, now=200)["ships"]}
    g = ships["Galaxy"]
    assert [(m["name"], m["price"], m["label"]) for m in g["modules"]] == [("Cargo", 7000, "10 Year")]
    assert [e["modules"] for e in g["editions"]] == [[], ["Med Bay"]]
    assert {k: v["scu"] for k, v in g["moduleGrids"].items()} == {"Cargo": 720, "Med Bay": 68}
    assert [m["name"] for m in ships["Aurora Mk II"]["modules"]] == ["Cargo"] and "modules" not in ships["Aurora"]

    by_name = {"galaxy": "G", "aurora": "A", "aurora mk ii": "A2"}
    assert module_of("Galaxy - Refinery Module - Warbond", by_name) == ("G", "Refinery")
    assert module_of("Aurora Mk II Combat Module", by_name) == ("A2", "Combat")
    assert module_of("Kruger Snub Laser Weapons Kit", by_name) == (None, "")
    assert is_module({"name": "Galaxy - Cargo Module", "gameItems": [{"kind": "SHIPMOD"}]})
    assert not is_module({"name": "Kruger Snub Laser Weapons Kit", "gameItems": [{"kind": "SHIPMOD"}]})
    assert not is_module({"name": "Shiv - Lunatic Bodykit", "gameItems": [{"kind": "SHIPMOD"}]})
