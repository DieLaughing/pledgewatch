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


def test_weapons_count_pilot_guns_and_slaveable_turrets_only():
    gun = lambda name, dps: {"name": name, "dps": dps}
    v = {"weaponry": {"fixed_weapons": {"weapons": [gun("C-788 Cannon", 800), gun("C-788 Cannon", 800)]},
                      "missiles": {"count": 16}},
         "turrets": {"manned": [{"is_pilot_slaveable": False, "weapons": [gun("AD4B", 1266)] * 2}],
                     "remote": [{"is_pilot_slaveable": True, "weapons": [gun("M5A Cannon", 680)] * 2}], "pdc": []}}
    assert weapons(v) == {"pilot": [[2, None, "C-788 Cannon", False], [2, None, "M5A Cannon", True]], "pilotDps": 2960,
                          "manned": 1, "remote": 1, "slaved": 1, "turretGuns": 2, "missiles": 16}
    assert weapons({"weaponry": None}) is None
