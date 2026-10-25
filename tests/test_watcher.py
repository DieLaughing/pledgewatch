from pw import db as store_db
from pw.watcher import FAILS_BEFORE_ALERT, check


def ship(sid, name, price=10000, available=True, limited=False, level="high"):
    return {"id": sid, "name": name, "url": f"https://example/{sid}", "image": "", "category": "Standalone Ships",
            "price": price, "list_price": price, "available": available, "limited": limited, "level": level, "qty": 0}


BASE = [ship("1", "Carrack", 60000), ship("2", "Gladius", 9000), ship("3", "Arrow", 7500)]


def kinds(events):
    return sorted((e["kind"], e.get("name")) for e in events)


def fresh(tmp_path, items=BASE):
    db = store_db.connect(str(tmp_path / "t.db"))
    assert check(db, items, now=1) == []  # first look is the baseline
    return db


def test_first_run_is_quiet(tmp_path):
    db = fresh(tmp_path)
    assert len(store_db.known(db)) == 3


def test_new_ship(tmp_path):
    db = fresh(tmp_path)
    assert kinds(check(db, BASE + [ship("9", "Idris-P", 150000, limited=True)], now=2)) == [("new", "Idris-P")]


def test_gone_needs_two_misses_then_back(tmp_path):
    db = fresh(tmp_path)
    assert check(db, BASE[:2], now=2) == []
    assert kinds(check(db, BASE[:2], now=3)) == [("gone", "Arrow")]
    assert check(db, BASE[:2], now=4) == []  # only said once
    assert kinds(check(db, BASE, now=5)) == [("back", "Arrow")]


def test_one_missed_read_is_forgiven(tmp_path):
    db = fresh(tmp_path)
    check(db, BASE[:2], now=2)
    assert check(db, BASE, now=3) == []
    assert store_db.known(db)["3"]["misses"] == 0


def test_sold_out_low_restock_price(tmp_path):
    idris = ship("9", "Idris-P", 150000, limited=True, level="high")
    db = fresh(tmp_path, BASE + [idris])
    assert kinds(check(db, BASE + [{**idris, "level": "medium"}], now=2)) == [("low", "Idris-P")]
    assert kinds(check(db, BASE + [{**idris, "available": False}], now=3)) == [("sold_out", "Idris-P")]
    assert kinds(check(db, BASE + [idris], now=4)) == [("restock", "Idris-P")]
    events = check(db, [{**BASE[0], "price": 54000}] + BASE[1:] + [idris], now=5)
    assert kinds(events) == [("price", "Carrack")] and events[0]["was"] == 60000


def test_unlimited_level_changes_are_ignored(tmp_path):
    db = fresh(tmp_path)
    assert check(db, [{**BASE[0], "level": "low"}] + BASE[1:], now=2) == []


def test_bad_read_is_not_a_mass_exodus(tmp_path):
    db = fresh(tmp_path)
    assert check(db, [], now=2) == []
    assert all(s["listed"] for s in store_db.known(db).values())


def test_store_down_alerts_once_then_recovers(tmp_path):
    db = fresh(tmp_path)
    results = [check(db, [], now=10 + i) for i in range(FAILS_BEFORE_ALERT + 2)]
    assert sum(len(r) for r in results) == 1 and results[FAILS_BEFORE_ALERT - 1][0]["kind"] == "store_down"
    assert kinds(check(db, BASE, now=100)) == [("store_ok", None)]
