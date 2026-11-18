import json
from pw import ingame
from pw.ingame import build_rows, by_hardpoint, history, weapons


def test_history_keeps_standalone_store_and_upgrade_rows():
    skus = [
        {"source": "pledge_store", "title": "Polaris", "price": 975, "is_warbond": False, "imported_at": "2026-10-24T00"},
        {"source": "pledge_store", "title": "Polaris", "price": 975, "is_warbond": False, "imported_at": "2026-10-24T05"},
        {"source": "pledge_store", "title": "2955 Best in Show Collection", "price": 1425, "is_warbond": True,
         "is_package": True, "imported_at": "2026-08-04"},
        {"source": "upgrade_api", "title": "Warbond Edition", "price": 700, "is_warbond": None, "imported_at": "2024-01-10"},
        {"source": "upgrade_api", "title": "Polaris Upgrade - 2021", "price": 750, "imported_at": "2024-01-10"},
    ]
    assert history(skus) == [["2024-01-10", 700, True, "upgrade", "Warbond Edition"],
                             ["2026-10-24", 975, False, "store", "Polaris"]]


def test_rows_merge_variants_and_join_uex_by_uuid_or_name():
    wiki = [
        {"id": 52, "uuid": "u-1", "name": "Cutlass Black", "insurance": {"claim_time": 10, "expedite_time": 3.3,
                                                                       "expedite_cost": 6251}, "skus": [], "version": "4.10.2-LIVE.1"},
        {"id": 52, "uuid": "u-2", "name": "Cutlass Black Variant", "insurance": {}, "skus": []},
        {"id": 116, "uuid": "u-9", "name": "Polaris", "insurance": {"claim_time": 75.8}, "skus": []},
    ]
    vehicles = [{"id": 1, "uuid": "u-2", "name": "Cutlass Black Variant"}, {"id": 2, "uuid": "", "name": "Polaris"}]
    buys = [{"id_vehicle": 1, "price_buy": 2010960, "terminal_name": "New Deal Lorville"},
            {"id_vehicle": 2, "price_buy": 1, "terminal_name": "Nowhere"}]
    rents = [{"id_vehicle": 1, "price_rent": 52920, "terminal_name": "Traveler"}]
    rows = {r[0]: r for r in build_rows(wiki, vehicles, buys, rents)}
    cutlass, polaris = rows["52"], rows["116"]
    assert cutlass[2:6] == (10, 3.3, 6251, "4.10.2")
    assert '"New Deal Lorville"' in cutlass[7] and '"Traveler"' in cutlass[8]
    assert '"Nowhere"' in polaris[7]  # UEX had no UUID for it, matched by name


def test_class_name_is_the_plain_variant():
    wiki = [{"id": 56, "name": "Cutlass Black", "class_name": "DRAK_Cutlass_Black_BIS2950", "insurance": {}, "skus": []},
            {"id": 56, "name": "Cutlass Black", "class_name": "DRAK_Cutlass_Black", "insurance": {}, "skus": []},
            {"id": 9, "name": "Nameless", "insurance": {}, "skus": []}]
    rows = {r[0]: r for r in build_rows(wiki, [], [], [])}
    assert rows["56"][11] == "DRAK_Cutlass_Black" and rows["9"][11] is None


def test_new_ships_the_wiki_hasnt_linked_yet_match_by_name():
    wiki = [{"id": None, "uuid": "u-c", "name": "Constellation Mk V Centaurus", "shipmatrix_name": None,
             "insurance": {"claim_time": 13.5, "expedite_time": 4.5, "expedite_cost": 6750}, "skus": []},
            {"id": None, "uuid": "u-x", "name": "Some Wikelo Special", "insurance": {}, "skus": []}]
    rows = build_rows(wiki, [], [], [], {"constellation mk v centaurus": "325"})
    assert [(r[0], r[2], r[4]) for r in rows] == [("325", 13.5, 6750)]


def test_weapons_list_every_gun_by_who_fires_it():
    gun = lambda name, dps: {"name": name, "dps": dps, "sustained_dps": dps / 2, "alpha": dps / 10}

    def turret(slave, guns, sizes, dps=None, fitted=(), types=()):
        return {"is_pilot_slaveable": slave, "weapons": guns, "weapon_sizes": sizes, "dps_total": dps,
                "sustained_dps_total": dps and dps / 2, "alpha_total": dps and dps / 10,
                "payload_class_names": list(fitted), "payload_types": list(types)}
    v = {"weaponry": {"fixed_weapons": {"weapons": [gun("C-788 Cannon", 800), gun("C-788 Cannon", 800)]},
                      "missiles": {"count": 16}},
         "turrets": {"manned": [turret(False, [gun("AD4B", 1266)] * 2, [4, 4], 2532)] * 2
                     + [turret(False, [], [2], fitted=["GRIN_TractorBeam_S2"])],  # tractor beam: left out
                     "remote": [turret(True, [gun("M5A Cannon", 680)] * 2, [3, 3], 1360),
                                turret(False, [], [4], fitted=["OCTO"], types=["MissileLauncher.MissileRack"]),
                                turret(False, [], [4], fitted=["UNLISTED"], types=["MissileLauncher.MissileRack"]),
                                turret(False, [], [9], fitted=["BEAM_S9"], types=["WeaponGun.Gun"]),
                                turret(False, [], [5])],  # nothing fitted: left out
                     "pdc": [turret(False, [gun("Swarm", 160)], [1], 160)]},
         "ports": [{"category_label": "Missile & Bomb Racks", "equipped_item_uuid": "r1"}] * 2}
    sizes = {"C-788 Cannon": 4, "AD4B": 4}  # M5A missing from the gun list: the turret's mount size is used
    classes = {"BEAM_S9": ("Laser Beam", 9)}
    racks = {"r1": (8, 2, "missile"), "OCTO": (8, 2, "missile")}
    assert weapons(v, sizes, classes, racks) == {
        "guns": [["pilot", "hardpoints", 1, [[2, 4, "C-788 Cannon"]], 1600, 800, 160],
                 ["both", "remote", 1, [[2, 3, "M5A Cannon"]], 1360, 680, 136],
                 ["gunner", "remote", 1, [[1, 9, "Laser Beam"]], 0, 0, 0],
                 ["gunner", "manned", 2, [[2, 4, "AD4B"]], 5064, 2532, 506],
                 ["gunner", "remote-missile", 1, [[1, 4, "missile rack"]], 0, 0, 0],
                 ["gunner", "remote-missile", 1, [[8, 2, "missiles"]], 0, 0, 0],
                 ["auto", "pdc", 1, [[1, 1, "Swarm"]], 160, 80, 16]],
        "pilot": [2960, 1480, 296], "missiles": [[24, 2, "missile"]], "missileCount": 16}
    assert weapons({"weaponry": None}, sizes, classes, racks) is None


def _port(name, cat=None, item=None, ports=None):
    return {"name": name, "category_label": cat, "equipped_item": item, "ports": ports}


def _gun(name, size, burst, sustained=None, alpha=None, dps=None):
    return {"type": "WeaponGun", "classification": "Ship.Weapon.Gun", "name": name, "size": size,
            "vehicle_weapon": {"damage": {"burst": burst, "sustained_60s": sustained, "alpha_total": alpha,
                                          "dps": dps or {}}}}


def _mount(name, cat, *guns, kind="Turret"):
    return _port(name, cat, {"type": kind}, [_port(f"gun{i}", None, g) for i, g in enumerate(guns)])


def test_guns_are_sorted_by_the_hardpoint_they_sit_on():
    """Tiburon: the wiki's summary has the remote turrets' cannons as the pilot's and no spine beam."""
    cannon = _gun("C-07T Cannon", 7, 2683.3, 2077.4, 4600)
    beam = _gun("Supremacy-10T Laser Beam", 10, None, dps={"energy": 18000})
    rhino = _gun("CF-447 Rhino Repeater", 4, 817.9, 414.5, 65.4)
    tractor = {"type": "WeaponGun", "classification": "Ship.UtilityWeapon.TractorBeam", "name": "Tractor"}
    detail = {"ports": [
        _port("hardpoint_weapon", "Weapons", beam),
        *[_mount(f"hardpoint_turret_{i}", "Remote Turrets", cannon) for i in range(4)],
        _mount("turret_rear", "Manned Turrets", rhino, rhino),
        _mount("tractor_turret", "Remote Turrets", tractor),  # a tractor beam: left out
        _port("hardpoint_rear", "Other", {"type": "AttachedPart"},  # MDC: the wiki's PDC sits inside a module
              [_mount("hardpoint_mdc_pdc", None, _gun("Torrent", 1, 360, 285, 18))]),
        _mount("hardpoint_door", "Other", _gun("YellowJacket", 1, 403, 338, 15), kind="WeaponMount"),
        _port("pod", "Turrets", {"type": "MissileLauncher"},  # missiles count as fitted, wherever the rack is
              [_port(f"m{i}", None, {"type": "Missile", "size": 3, "classification": "Ship.Missile.Missile"})
               for i in range(2)] + [_port("r", None, {"type": "Missile", "size": 0,
                                                       "classification": "Ship.Missile.Rocket"})]),
    ]}
    listed = {"manned": [{"hardpoint_name": "turret_rear", "is_pilot_slaveable": False, "weapon_sizes": [4, 4],
                          "weapons": [{"name": "CF-447 Rhino Repeater"}] * 2}],
              "pdc": [{"hardpoint_name": "hardpoint_mdc_pdc", "weapons": []}],
              "remote": [{"hardpoint_name": "torpedo_camera", "payload_class_names": ["RACK"],
                          "payload_types": ["MissileLauncher.MissileRack"]}]}  # not on a hardpoint: kept
    s = by_hardpoint(detail, listed)
    assert s["fixed"] == [{"name": "Supremacy-10T Laser Beam", "size": 10, "dps": 18000, "sustained_dps": 0, "alpha": 0}]
    v = {"weaponry": {"fixed_weapons": {"weapons": [{"name": "C-07T Cannon", "dps": 2683.3}] * 4}}, "turrets": listed}
    w = weapons(v, {}, {}, {"RACK": (8, 3, "missile")}, s)
    assert w["guns"] == [["pilot", "hardpoints", 1, [[1, 10, "Supremacy-10T Laser Beam"]], 18000, 0, 0],
                         ["gunner", "remote", 4, [[1, 7, "C-07T Cannon"]], 10733, 8310, 18400],
                         ["gunner", "manned", 1, [[2, 4, "CF-447 Rhino Repeater"]], 1636, 829, 131],
                         ["gunner", "manned", 1, [[1, 1, "YellowJacket"]], 403, 338, 15],
                         ["gunner", "remote-missile", 1, [[8, 3, "missiles"]], 0, 0, 0],
                         ["auto", "pdc", 1, [[1, 1, "Torrent"]], 360, 285, 18]]
    assert w["pilot"] == [18000, 0, 0]
    assert w["missiles"] == [[2, 3, "missile"], [1, None, "rocket"]]


def test_a_hardpoints_own_turret_category_beats_the_wikis_list():
    """Liberator: point defence the wiki lists nowhere; a turret it lists as manned that is really remote."""
    swarm = _gun("Swarm", 1, 166, 74, 10)
    detail = {"ports": [_mount("pdt", "PDC Turrets", swarm), _mount("top", "Remote Turrets", swarm)]}
    s = by_hardpoint(detail, {"manned": [{"hardpoint_name": "top", "is_pilot_slaveable": True}]})
    assert [len(s["turrets"][m]) for m in ("manned", "remote", "pdc")] == [0, 1, 1]
    assert s["turrets"]["remote"][0]["is_pilot_slaveable"] is True


def test_only_ships_the_summary_may_have_wrong_are_reread():
    port = lambda cat, typ="Turret": {"category_label": cat, "type": typ, "equipped_item_uuid": "x"}
    ok = {"weaponry": {"fixed_weapons": {"weapons": [{"name": "M5A"}]}}, "ports": [port("Remote Turrets")],
          "turrets": {"remote": [{"weapons": [{"name": "M5A"}]}]}}
    assert not ingame._misfiled(ok)
    assert ingame._misfiled({**ok, "turrets": {}})  # a remote turret the wiki doesn't list
    assert ingame._misfiled({**ok, "ports": ok["ports"] + [port("Weapons", "WeaponGun")]})  # a gun on the hull
    assert ingame._misfiled(ok, unsure={"M5A"})  # the gun's name covers several sizes
    assert not ingame._misfiled({"weaponry": None})


def test_hardpoints_are_cached_per_game_version_and_one_failure_stops_reads(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        if "bad" in url:
            raise OSError("wiki down")
        return {"data": {"ports": []}}
    monkeypatch.setattr(ingame, "_get", get)
    monkeypatch.setattr(ingame, "SHIP_PAUSE", 0)
    cached, reach = {"a": ["4.3", "old sort"], "b": ["4.2", "stale"]}, {"ok": True}
    assert ingame._hardpoints({"uuid": "a", "version": "4.3"}, cached, reach) == ["4.3", "old sort"]
    assert ingame._hardpoints({"uuid": "c", "version": "4.3"}, cached, reach)[1]["fixed"] == []
    assert ingame._hardpoints({"uuid": "bad", "version": "4.3"}, cached, reach) is None
    # not read while the wiki is down, and kept under its old version so it's read again on the next refresh
    assert ingame._hardpoints({"uuid": "b", "version": "4.3"}, cached, reach) == ["4.2", "stale"]
    assert len(calls) == 2


def test_a_failed_refresh_keeps_the_ships_it_read_for_the_retry(monkeypatch):
    from pw import db as pdb
    ship = {"uuid": "u1", "version": "4.3", "name": "Tiburon", "weaponry": {}, "turrets": {},
            "ports": [{"type": "WeaponGun", "equipped_item_uuid": "x"}]}
    reads, fail = [], {"uex": True}

    def get(url):
        if "/vehicles/" in url:
            reads.append(url)
            return {"data": {"ports": []}}
        if "items" in url:
            return {"data": [], "meta": {"last_page": 1}}
        if "vehicles?" in url:
            return {"data": [dict(ship, weaponry={"fixed_weapons": {"weapons": [{"name": "G"}]}})],
                    "meta": {"last_page": 1}}
        if fail["uex"]:
            raise OSError("reset")
        return {"data": []}
    monkeypatch.setattr(ingame, "_get", get)
    monkeypatch.setattr(ingame, "SHIP_PAUSE", 0)
    monkeypatch.setattr(ingame, "_unsaved", {})
    con = pdb.connect(":memory:")
    ingame.refresh(con, now=1000)
    assert len(reads) == 1 and con.execute("SELECT count(*) FROM ingame").fetchone()[0] == 0
    fail["uex"] = False
    ingame.refresh(con, now=1300)
    assert len(reads) == 1  # not read again
    assert "u1" in json.loads(con.execute("SELECT value FROM state WHERE key='ingame_hardpoints'").fetchone()[0])
    assert ingame._unsaved == {}


def test_turrets_the_wiki_doesnt_list_get_their_pilot_slaving_from_the_game_files(monkeypatch):
    """Corsair: the tail turret isn't in the wiki's turret list, so the wiki has no is_pilot_slaveable for it."""
    badger = _gun("CF-227 Badger Repeater", 2, 328, 167.5, 26)
    detail = {"ports": [_mount("hardpoint_tail_turret", "Remote Turrets", badger, badger),
                        _mount("hardpoint_bridge", "Remote Turrets", badger),
                        _mount("hardpoint_manned_left", "Manned Turrets", badger, badger)]}
    listed = {"manned": [{"hardpoint_name": "hardpoint_manned_left", "is_pilot_slaveable": False}]}
    urls = []

    def get(url):
        urls.append(url)
        if "scunpacked" not in url:
            return {"data": detail}
        return {"Loadout": [{"HardpointName": "hardpoint_tail_turret", "IsPilotSlaveable": True},
                            {"HardpointName": "hardpoint_bridge", "IsPilotSlaveable": False},
                            {"HardpointName": "hardpoint_manned_left", "IsPilotSlaveable": True}]}
    monkeypatch.setattr(ingame, "_get", get)
    monkeypatch.setattr(ingame, "SHIP_PAUSE", 0)
    v = {"uuid": "u", "version": "4.3", "class_name": "DRAK_Corsair", "turrets": listed,
         "weaponry": {"fixed_weapons": {"weapons": []}}}
    version, sorted_ = ingame._hardpoints(v, {}, {"ok": True})
    assert version == "4.3" and urls[-1].endswith("/ships/drak_corsair.json")
    rows = weapons(v, {}, {}, {}, sorted_)["guns"]
    assert [(r[0], r[1], r[3][0][0]) for r in rows] == [("both", "remote", 2), ("gunner", "manned", 2),  # wiki's flag kept
                                                       ("gunner", "remote", 1)]

    def down(url):
        if "scunpacked" in url:
            raise OSError("github down")
        return {"data": detail}
    monkeypatch.setattr(ingame, "_get", down)
    version, sorted_ = ingame._hardpoints(v, {}, {"ok": True})
    assert version is None  # read again on the next refresh
    assert all(t["is_pilot_slaveable"] is None for t in sorted_["turrets"]["remote"])
