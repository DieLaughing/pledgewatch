from pw.ingame import build_rows, history, weapons


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


def test_weapons_list_every_gun_by_who_fires_it():
    gun = lambda name, dps: {"name": name, "dps": dps}
    turret = lambda slave, guns, sizes, dps: {"is_pilot_slaveable": slave, "weapons": guns, "weapon_sizes": sizes,
                                              "dps_total": dps}
    v = {"weaponry": {"fixed_weapons": {"weapons": [gun("C-788 Cannon", 800), gun("C-788 Cannon", 800)]},
                      "missiles": {"count": 16}},
         "turrets": {"manned": [turret(False, [gun("AD4B", 1266)] * 2, [4, 4], 2532)] * 2,
                     "remote": [turret(True, [gun("M5A Cannon", 680)] * 2, [3, 3], 1360), turret(False, [], [4], 0),
                                turret(False, [], [], 0)],
                     "pdc": [turret(False, [gun("Swarm", 160)], [1], 160)]},
         "ports": [{"category_label": "Missile & Bomb Racks", "equipped_item_uuid": "r1"}] * 2}
    sizes = {"C-788 Cannon": 4, "AD4B": 4}  # M5A missing from the gun list: the turret's mount size is used
    racks = {"r1": (8, 2, "missile")}
    assert weapons(v, sizes, racks) == {
        "guns": [["pilot", "hardpoints", 1, [[2, 4, "C-788 Cannon"]], 1600],
                 ["pilot", "remote", 1, [[2, 3, "M5A Cannon"]], 1360],
                 ["gunner", "manned", 2, [[2, 4, "AD4B"]], 5064],
                 ["gunner", "remote", 1, [[1, 4, ""]], 0],
                 ["auto", "pdc", 1, [[1, 1, "Swarm"]], 160]],
        "pilotDps": 2960, "missiles": [[16, 2, "missile"]], "missileCount": 16}
    assert weapons({"weaponry": None}, sizes, racks) is None
