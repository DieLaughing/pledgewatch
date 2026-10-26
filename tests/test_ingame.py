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
