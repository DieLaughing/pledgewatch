"""In-game side of each ship, refreshed once a day.

- Star Citizen Wiki API (api.star-citizen.wiki, content CC BY-SA 4.0): insurance claim and expedite times and the
  expedite cost in aUEC (from the game files, with the game version), the ship's pledge store history (every
  edition and price the wiki has seen, with dates) and its weapons: which guns the pilot fires, and the turrets.
  Its vehicle id is the Ship Matrix id. The wiki's weapon summary sometimes files turret guns as the pilot's (Tiburon,
  Corsair, Hull C) or leaves a gun out (the Tiburon's beam); those ships are re-read gun by gun from their hardpoints.
- scunpacked-data (github.com/StarCitizenWiki/scunpacked-data, the wiki team's game file dump): whether the pilot can
  slave a turret, for turrets the wiki's turret list leaves out (it only carries that flag for the ones it lists).
- UEX (uexcorp.space): where a ship can be bought or rented in game and for how much aUEC. Joined to the wiki by the
  game's vehicle UUID.
"""
import json
import logging
import re
import time
import urllib.request

from .commands import norm
from .store import USER_AGENT

log = logging.getLogger("pledgewatch")

WIKI = "https://api.star-citizen.wiki/api/v2/vehicles?page%5Bsize%5D=50&page%5Bnumber%5D={}"
VEHICLE = "https://api.star-citizen.wiki/api/v2/vehicles/{}"  # one ship, hardpoints nested (~500 KB)
SCUNPACKED = "https://raw.githubusercontent.com/StarCitizenWiki/scunpacked-data/master/ships/{}.json"  # ~200 KB
ITEMS = "https://api.star-citizen.wiki/api/v2/items?filter%5Btype%5D={}&page%5Bsize%5D=200&page%5Bnumber%5D={}"
UEX = "https://api.uexcorp.space/2.0/"
REFRESH = 86400
PAUSE = 1.5  # between wiki pages; each is ~3 MB
SHIP_PAUSE = 0.5  # between single ships read for their hardpoints (~100 after a game patch, about 2 minutes)
_unsaved = {}  # ships read by a refresh that then failed, so the retry doesn't read them again
KEEP = ("id", "uuid", "name", "shipmatrix_name", "class_name", "insurance", "skus", "version")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _items(kind):
    """Every item of one type (pages of 200, the API's most)."""
    out, page = [], 1
    while True:
        d = _get(ITEMS.format(kind, page))
        out += d["data"]
        if page >= d["meta"]["last_page"]:
            return out
        page += 1


def refresh(db, now=None, force=False):
    now = int(now or time.time())
    last = db.execute("SELECT value FROM state WHERE key='ingame_at'").fetchone()
    cached = db.execute("SELECT value FROM state WHERE key='ingame_hardpoints'").fetchone()
    if not force and last and cached and now - json.loads(last[0]) < REFRESH:
        return
    # Ships re-read from their hardpoints, {uuid: [game version, by_hardpoint()]}: fetched again only after a patch.
    cached, ports, reach = {**(json.loads(cached[0]) if cached else {}), **_unsaved}, {}, {"ok": True}
    try:
        # Ship guns and missile racks (~3 MB together): the vehicle list doesn't nest guns in their mounts or say
        # what a rack holds, so sizes and rack capacities come from here.
        guns = [g for g in _items("WeaponGun") if g.get("name")]
        # A few names cover guns of different sizes (M9A Cannon is S7 to S12): those ships are read from their
        # hardpoints, and the name gives no size.
        named = {}
        for g in guns:
            named.setdefault(g["name"], set()).add(g.get("size"))
        sizes = {n: s.pop() for n, s in named.items() if len(s) == 1}
        unsure = set(named) - set(sizes)
        classes = {g["class_name"]: (g["name"], g.get("size")) for g in guns if g.get("class_name")}
        racks = {}  # by uuid (ship hardpoints) and class name (missile turrets name their rack's class)
        for r in _items("MissileLauncher"):
            if r.get("missile_rack"):
                racks[r["uuid"]] = racks[r.get("class_name") or r["uuid"]] = _rack(r)
        wiki, page = [], 1
        while True:
            d = _get(WIKI.format(page))
            # Each vehicle has ~77 fields (~60 KB); keep the few we use so a refresh stays well inside the memory cap.
            for v in d["data"]:
                arms = weapons(v, sizes, classes, racks)
                if v.get("uuid") and (_misfiled(v, unsure) or arms and _missiles_short(arms)):
                    entry = _hardpoints(v, cached, reach)
                    if entry:
                        ports[v["uuid"]] = entry
                        arms = weapons(v, sizes, classes, racks, entry[1])
                wiki.append({**{k: v.get(k) for k in KEEP}, "weapons": arms})
            del d["data"]
            if page >= d["meta"]["last_page"]:
                break
            page += 1
            time.sleep(PAUSE)
        vehicles = _get(UEX + "vehicles")["data"]
        buys = _get(UEX + "vehicles_purchases_prices_all")["data"]
        rents = _get(UEX + "vehicles_rentals_prices_all")["data"]
    except Exception as e:
        _unsaved.update(ports)
        log.warning("couldn't refresh in-game data (%d ships re-read kept for the retry): %s", len(_unsaved), e)
        return
    ids = {norm(c["name"]): c["mid"] for c in db.execute("SELECT name, mid FROM catalog WHERE mid IS NOT NULL")}
    rows = build_rows(wiki, vehicles, buys, rents, ids)
    with db:
        db.execute("DELETE FROM ingame")
        db.executemany("INSERT OR REPLACE INTO ingame VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (("ingame_at", json.dumps(now)), ("ingame_hardpoints", json.dumps(ports))))
    _unsaved.clear()
    log.info("in-game data: %d ships from the wiki, %d buy and %d rent prices", len(rows), len(buys), len(rents))


def build_rows(wiki, vehicles, buys, rents, ids=None):
    """One row per Ship Matrix id: (mid, uuid, claim min, expedite min, expedite aUEC, version, history, buy, rent,
    wiki name, weapons, class name). Several wiki entries can share an id (variants): insurance and weapons come from the one with
    insurance data, and prices and history are merged across all of them. UEX is matched by game UUID, or by name when UEX has no UUID.
    `ids` ({normalised Ship Matrix name: id}) places wiki entries that aren't linked to the Ship Matrix yet, which
    happens with newly released ships (Constellation Mk V Centaurus), by their exact name."""
    uex = {v["id"]: (v.get("uuid") or "", norm(v.get("name") or "")) for v in vehicles}
    prices = {}
    for kind, rows, field in (("buy", buys, "price_buy"), ("rent", rents, "price_rent")):
        for p in rows:
            u, n = uex.get(p.get("id_vehicle"), ("", norm(p.get("vehicle_name") or "")))
            if p.get(field):
                row = [p[field], p.get("terminal_name") or "", p.get("date_modified") or 0]
                for key in ((u and ("uuid", u)), ("name", n)):
                    if key:
                        prices.setdefault((key, kind), []).append(row)
    groups = {}
    ids = ids or {}
    for v in wiki:
        mid = v.get("id") or next((ids[norm(n)] for n in (v.get("shipmatrix_name"), v.get("name"))
                                   if n and norm(n) in ids), None)
        if mid:
            groups.setdefault(str(mid), []).append(v)
    out = []
    for mid, vs in groups.items():
        main = max(vs, key=lambda v: (bool((v.get("insurance") or {}).get("claim_time")), len(v.get("skus") or [])))
        ins = main.get("insurance") or {}
        found = {"buy": {}, "rent": {}}
        for v in vs:
            keys = [("uuid", v["uuid"])] if v.get("uuid") else []
            keys += [("name", norm(n)) for n in (v.get("name"), v.get("shipmatrix_name")) if n]
            for kind in found:
                for key in keys:
                    for row in prices.get((key, kind), []):
                        found[kind][(row[0], row[1])] = row
        skus = [s for v in vs for s in (v.get("skus") or [])]
        # The game's class name (RSI_Galaxy) is how erkul.games opens a ship. Variants share an id; the plain one has
        # the shortest name (DRAK_Cutlass_Black, not DRAK_Cutlass_Black_BIS2950 or AEGS_..._Display).
        classes = [v["class_name"] for v in vs if v.get("class_name")]
        out.append((str(mid), main.get("uuid") or "", ins.get("claim_time"), ins.get("expedite_time"),
                    ins.get("expedite_cost"), (main.get("version") or "").split("-")[0], json.dumps(history(skus)),
                    json.dumps(sorted(found["buy"].values())), json.dumps(sorted(found["rent"].values())),
                    main.get("name") or "", json.dumps(main.get("weapons")) if main.get("weapons") else None,
                    min(classes, key=len) if classes else None))
    return out


def _rack(r):
    """(missiles it holds, their size, 'torpedo', 'bomb' or 'missile')."""
    kinds = {t for p in r.get("ports") or [] for c in p.get("compatible_types") or [] for t in c.get("sub_types") or []}
    kind = "torpedo" if "Torpedo" in kinds else "bomb" if "Bomb" in kinds else "missile"
    return r["missile_rack"].get("missile_count") or 0, r["missile_rack"].get("missile_size"), kind


TURRET_PORTS = {"Remote Turrets": "remote", "Manned Turrets": "manned", "PDC Turrets": "pdc"}


def _misfiled(v, unsure=frozenset()):
    """Could the wiki's weapon summary have this ship's guns in the wrong place? Yes when its turret lists don't match
    the turret hardpoints that have something fitted, or a gun sits straight on the hull (a spine beam). About 90
    ships, most of them fine (a remote turret holding a tractor beam); the rest of the fleet matches its hardpoints.
    Also yes when it carries a gun whose name doesn't say its size (unsure), so the hardpoint can."""
    w = v.get("weaponry")
    if not w:
        return False
    t, top = v.get("turrets") or {}, [p for p in v.get("ports") or [] if p.get("equipped_item_uuid")]
    names = {g.get("name") for g in (w.get("fixed_weapons") or {}).get("weapons") or []}
    names |= {g.get("name") for m in t.values() for x in m or [] for g in x.get("weapons") or []}
    return (any(sum(p.get("category_label") == c for p in top) != len(t.get(m) or []) for c, m in TURRET_PORTS.items())
            or any(p.get("type") == "WeaponGun" for p in top) or bool(names & unsure))


def _missiles_short(arms):
    """Do the racks we can see from the vehicle list hold a different number of missiles than the wiki counts? Racks
    inside turrets and pods (Nova, Storm AA, Ballista) and bombs (A1 Spirit) aren't visible there."""
    return sum(n for n, _, _ in arms["missiles"]) != arms["missileCount"]


def _hardpoints(v, cached, reach):
    """[game version, by_hardpoint()] for one ship: from the cache while the game version is the same, else from the
    wiki. After one failed read the rest of this refresh doesn't try (reach), so a wiki outage can't hold up the store
    checks; those ships keep their cached entry (with its old version, so it's read again next time), else None and
    the wiki's summary until tomorrow. An entry whose turret flags couldn't be filled in is cached with no version,
    so it's read again on the next refresh."""
    hit = cached.get(v["uuid"])
    if hit and hit[0] == v.get("version"):
        return hit
    if reach["ok"]:
        try:
            d = _get(VEHICLE.format(v["uuid"]))["data"]
            time.sleep(SHIP_PAUSE)
            sorted_ = by_hardpoint(d, v.get("turrets") or {})
            return [v.get("version") if _slaving(v.get("class_name"), sorted_) else None, sorted_]
        except Exception as e:
            reach["ok"] = False
            log.warning("couldn't read %s's hardpoints, using cached or summary weapons: %s", v.get("name"), e)
    return hit


def _slaving(class_name, sorted_):
    """Fill in who can fire the turrets the wiki doesn't list (the Corsair's tail turret, the Tiburon's four) from the
    game files' IsPilotSlaveable, matched by hardpoint. Wherever both have the flag they agree (158 turrets, checked
    2026-11-18). False when the file couldn't be read; the turrets stay gunner-only until the next try."""
    unknown = [t for m in ("manned", "remote") for t in sorted_["turrets"][m]
               if t.get("is_pilot_slaveable") is None and t.get("hardpoint")]
    if not unknown or not class_name:
        return True
    try:
        flags = {p.get("HardpointName"): p.get("IsPilotSlaveable")
                 for p in _get(SCUNPACKED.format(class_name.lower())).get("Loadout") or []}
    except Exception as e:
        log.warning("couldn't read %s's turret controls from scunpacked-data: %s", class_name, e)
        return False
    for t in unknown:
        if flags.get(t["hardpoint"]) is not None:
            t["is_pilot_slaveable"] = flags[t["hardpoint"]]
    return True


def _gun(item):
    """A gun's figures from its item record. A beam has no shots, so no alpha, and the wiki gives no sustained DPS."""
    d = (item.get("vehicle_weapon") or {}).get("damage") or {}
    dps = d.get("burst") or sum((d.get("dps") or {}).values())
    return {"name": item.get("name"), "size": item.get("size"), "dps": dps,
            "sustained_dps": d.get("sustained_60s") or 0, "alpha": d.get("alpha_total") or 0}


MISSILE_KINDS = {"Ship.Missile.Torpedo": "torpedo", "Ship.Missile.Rocket": "rocket", "Ship.Bomb": "bomb"}


def by_hardpoint(detail, turrets):
    """Every gun on the ship sorted by the hardpoint it sits on, in the shapes weapons() reads:
    {"fixed": [gun], "turrets": {"manned"|"remote"|"pdc": [turret]}, "missiles": [[count, size, kind]]}, the
    missiles being every one fitted, wherever its rack is. A turret the wiki lists keeps its entry (who
    can fire it, missile racks) with the guns actually in it; a hardpoint's own category (Remote/Manned/PDC Turrets)
    beats the list the wiki put it in. Turret hardpoints and door guns the wiki doesn't list become crewed turrets; any
    other gun is the pilot's."""
    listed = {x["hardpoint_name"]: (m, x) for m in ("manned", "remote", "pdc") for x in turrets.get(m) or []
              if x.get("hardpoint_name")}
    fixed, out = [], {"manned": [], "remote": [], "pdc": []}

    def item(p):
        return p.get("equipped_item") if isinstance(p.get("equipped_item"), dict) else {}

    def children(p):
        return (p.get("ports") or []) + (item(p).get("ports") or [])

    def guns_in(p):
        it = item(p)
        if it.get("type") == "WeaponGun":
            return [_gun(it)] if (it.get("classification") or "").startswith("Ship.Weapon") else []
        return [g for c in children(p) for g in guns_in(c)]

    def turret(x, guns, hardpoint=None):
        return {"hardpoint": hardpoint, "is_pilot_slaveable": x.get("is_pilot_slaveable"), "weapons": guns,
                "weapon_sizes": x.get("weapon_sizes") or [g["size"] for g in guns],
                "payload_class_names": x.get("payload_class_names") or [], "payload_types": x.get("payload_types") or []}

    def visit(p, cat, top):
        name = p.get("name")
        if name in listed and item(p).get("type") != "WeaponGun":
            m, x = listed.pop(name)
            guns = guns_in(p)
            out[TURRET_PORTS.get(cat, m)].append(turret(x, guns or x.get("weapons") or [], name))
        elif (top and cat in TURRET_PORTS) or item(p).get("type") == "WeaponMount":  # WeaponMount: a crew door gun
            guns = guns_in(p)
            if guns:  # else a camera, a tractor beam or nothing fitted
                out[TURRET_PORTS.get(cat, "manned")].append(turret({}, guns, name))
        elif item(p).get("type") == "WeaponGun":
            fixed.extend(guns_in(p))
        else:
            for c in children(p):
                visit(c, cat, False)

    missiles = {}

    def ordnance(p):
        it = item(p)
        if it.get("type") in ("Missile", "Bomb"):
            key = (it.get("size") or None, MISSILE_KINDS.get(it.get("classification"), "missile"))
            missiles[key] = missiles.get(key, 0) + 1
        for c in children(p):
            ordnance(c)

    for p in detail.get("ports") or []:
        visit(p, p.get("category_label"), True)
        ordnance(p)
    for m, x in listed.values():  # turrets the wiki lists on a hardpoint it doesn't show: kept as they are
        out[m].append(turret(x, x.get("weapons") or []))
    return {"fixed": fixed, "turrets": out,
            "missiles": [[n, size, kind] for (size, kind), n in sorted(missiles.items(), key=lambda x: -(x[0][0] or 0))]}


def weapons(v, sizes, classes, racks, sorted_=None):
    """Every gun and missile turret on the ship's stock loadout, grouped by who fires it, plus its missiles:
    {"guns": [[who, mount, how many mounts, [[count, size, gun]] per mount, DPS, sustained DPS, alpha]],
     "pilot": [DPS, sustained, alpha], "missiles": [[count, size, kind]], "missileCount"}.
    who is pilot (their own guns), pilot or gunner (turrets the pilot can slave to their trigger), gunner (crewed and
    remote turrets) or auto (point defence). Damage figures are for the whole row: every mount, every gun firing.
    A missile turret's guns are its missiles ([[8, 2, "missiles"]], or [[1, 4, "missile rack"]] when the wiki doesn't
    list the rack) and its damage is 0, as is a gun the wiki names on a turret but has no figures for (Mauler's S9
    beam). Tractor beams and turrets with nothing fitted are left out. The wiki's own pilot DPS isn't used: on some
    ships (Polaris) it counts a crewed turret. sorted_ (by_hardpoint()) replaces the wiki's gun lists when the ship
    was re-read from its hardpoints. None when the wiki has no weapon data."""
    w, t = v.get("weaponry"), v.get("turrets") or {}
    if not w:
        return None
    fixed = (w.get("fixed_weapons") or {}).get("weapons") or []
    if sorted_ is not None:
        fixed, t = sorted_["fixed"], sorted_["turrets"]

    def kit(guns, fallback=()):
        """[[count, size, name]], most first; sizes from the gun list, else the mount's."""
        out = {}
        for i, g in enumerate(guns):
            size = g.get("size") or sizes.get(g.get("name")) or (fallback[i] if i < len(fallback) else None)
            out[(size, g.get("name") or "?")] = out.get((size, g.get("name") or "?"), 0) + 1
        return [[n, size, name] for (size, name), n in sorted(out.items(), key=lambda x: (-(x[0][0] or 0), x[0][1]))]

    def damage(guns):
        return [sum(g.get(k) or 0 for g in guns) for k in ("dps", "sustained_dps", "alpha")]

    rows, missiles = {}, {}
    if fixed:
        rows[("pilot", "hardpoints", "")] = [1, kit(fixed), damage(fixed)]
    for mount in ("manned", "remote", "pdc"):
        for x in t.get(mount) or []:
            guns = x.get("weapons") or []
            who = "auto" if mount == "pdc" else "both" if x.get("is_pilot_slaveable") else "gunner"
            each, kind = kit(guns, x.get("weapon_sizes") or []), mount
            if not guns:
                fitted = x.get("payload_class_names") or []
                held = [racks[c] for c in fitted if c in racks]
                named = [classes[c] for c in fitted if c in classes]
                if held:  # a missile turret (890 Jump)
                    each, kind = [[n, size, f"{k}s"] for n, size, k in held], mount + "-missile"
                    for n, size, k in held:
                        missiles[(size, k)] = missiles.get((size, k), 0) + n
                elif any("MissileLauncher" in (p or "") for p in x.get("payload_types") or []):  # Polaris, Ballista
                    each, kind = [[1, max(x.get("weapon_sizes") or [0]) or None, "missile rack"]], mount + "-missile"
                elif named:
                    each = [[len(x.get("weapon_sizes") or [1]), named[0][1], named[0][0]]]
                else:
                    continue  # a camera, a tractor beam or nothing fitted
            row = rows.setdefault((who, kind, json.dumps(each)), [0, each, [0, 0, 0]])
            row[0] += 1
            totals = [x.get("dps_total"), x.get("sustained_dps_total"), x.get("alpha_total")]
            row[2] = [a + (b if b is not None else c) for a, b, c in zip(row[2], totals, damage(guns))]
    order = {"pilot": 0, "both": 1, "gunner": 2, "auto": 3}
    guns = [[who, mount, n, each, *map(round, dmg)] for (who, mount, _), (n, each, dmg) in rows.items()]
    guns.sort(key=lambda r: (order[r[0]], "missile" in r[1], -max((g[1] or 0) for g in r[3])))
    for p in v.get("ports") or []:
        rack = racks.get(p.get("equipped_item_uuid")) if p.get("category_label") == "Missile & Bomb Racks" else None
        if rack and rack[0]:
            missiles[rack[1:]] = missiles.get(rack[1:], 0) + rack[0]
    pilot = [sum(r[i] for r in guns if r[0] in ("pilot", "both")) for i in (4, 5, 6)]
    if sorted_ is not None and sorted_.get("missiles") is not None:  # what's fitted, not what the racks could hold
        missiles = {(size, kind): n for n, size, kind in sorted_["missiles"]}
    return {"guns": guns, "pilot": pilot,
            "missiles": [[n, size, kind] for (size, kind), n in sorted(missiles.items(), key=lambda x: -(x[0][0] or 0))],
            "missileCount": (w.get("missiles") or {}).get("count") or 0}


PACK = re.compile(r"\b(pack|package|collection|bundle)\b", re.I)


def history(skus):
    """Standalone editions the wiki has seen in the pledge store and RSI's upgrade store: [date, price in dollars,
    warbond?, 'store' or 'upgrade', title], oldest first, duplicates and packs out. Upgrade-store entries don't flag warbond; their title
    ('Warbond Edition') does."""
    seen, out = set(), []
    for s in skus:
        title = s.get("title") or ""
        if s.get("source") not in (None, "pledge_store", "upgrade_api") or not s.get("price"):
            continue
        if s.get("is_package") or PACK.search(title) or " upgrade - " in title.lower():
            continue
        wb = s.get("is_warbond")
        if wb is None:
            wb = "warbond" in title.lower()
        source = "upgrade" if s.get("source") == "upgrade_api" else "store"
        row = [(s.get("imported_at") or "")[:10], s["price"], bool(wb), source, title]
        key = (row[0], row[1], row[2], source)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return sorted(out)
