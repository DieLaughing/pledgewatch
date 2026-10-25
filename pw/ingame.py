"""In-game side of each ship, refreshed once a day.

- Star Citizen Wiki API (api.star-citizen.wiki, content CC BY-SA 4.0): insurance claim and expedite times and the
  expedite cost in aUEC (from the game files, with the game version), the ship's pledge store history (every
  edition and price the wiki has seen, with dates) and its weapons: which guns the pilot fires, and the turrets.
  Its vehicle id is the Ship Matrix id.
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
ITEMS = "https://api.star-citizen.wiki/api/v2/items?filter%5Btype%5D={}&page%5Bsize%5D=500"
UEX = "https://api.uexcorp.space/2.0/"
REFRESH = 86400
PAUSE = 1.5  # between wiki pages; each is ~3 MB
KEEP = ("id", "uuid", "name", "shipmatrix_name", "insurance", "skus", "version")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def refresh(db, now=None, force=False):
    now = int(now or time.time())
    last = db.execute("SELECT value FROM state WHERE key='ingame_at'").fetchone()
    if not force and last and now - json.loads(last[0]) < REFRESH:
        return
    try:
        # Ship guns and missile racks (~3 MB together): the vehicle list doesn't nest guns in their mounts or say
        # what a rack holds, so sizes and rack capacities come from here.
        sizes = {g["name"]: g.get("size") for g in _get(ITEMS.format("WeaponGun"))["data"] if g.get("name")}
        racks = {r["uuid"]: _rack(r) for r in _get(ITEMS.format("MissileLauncher"))["data"] if r.get("missile_rack")}
        wiki, page = [], 1
        while True:
            d = _get(WIKI.format(page))
            # Each vehicle has ~77 fields (~60 KB); keep the few we use so a refresh stays well inside the memory cap.
            wiki += [{**{k: v.get(k) for k in KEEP}, "weapons": weapons(v, sizes, racks)} for v in d["data"]]
            del d["data"]
            if page >= d["meta"]["last_page"]:
                break
            page += 1
            time.sleep(PAUSE)
        vehicles = _get(UEX + "vehicles")["data"]
        buys = _get(UEX + "vehicles_purchases_prices_all")["data"]
        rents = _get(UEX + "vehicles_rentals_prices_all")["data"]
    except Exception as e:
        log.warning("couldn't refresh in-game data: %s", e)
        return
    rows = build_rows(wiki, vehicles, buys, rents)
    with db:
        db.execute("DELETE FROM ingame")
        db.executemany("INSERT OR REPLACE INTO ingame VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        db.execute("INSERT INTO state (key, value) VALUES ('ingame_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now),))
    log.info("in-game data: %d ships from the wiki, %d buy and %d rent prices", len(rows), len(buys), len(rents))


def build_rows(wiki, vehicles, buys, rents):
    """One row per Ship Matrix id: (mid, uuid, claim min, expedite min, expedite aUEC, version, history, buy, rent,
    wiki name, weapons). Several wiki entries can share an id (variants): insurance and weapons come from the one with
    insurance data, and prices and history are merged across all of them. UEX is matched by game UUID, or by name when UEX has no UUID."""
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
    for v in wiki:
        if v.get("id"):
            groups.setdefault(v["id"], []).append(v)
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
        out.append((str(mid), main.get("uuid") or "", ins.get("claim_time"), ins.get("expedite_time"),
                    ins.get("expedite_cost"), (main.get("version") or "").split("-")[0], json.dumps(history(skus)),
                    json.dumps(sorted(found["buy"].values())), json.dumps(sorted(found["rent"].values())),
                    main.get("name") or "", json.dumps(main.get("weapons")) if main.get("weapons") else None))
    return out


def _rack(r):
    """(missiles it holds, their size, 'torpedo', 'bomb' or 'missile')."""
    kinds = {t for p in r.get("ports") or [] for c in p.get("compatible_types") or [] for t in c.get("sub_types") or []}
    kind = "torpedo" if "Torpedo" in kinds else "bomb" if "Bomb" in kinds else "missile"
    return r["missile_rack"].get("missile_count") or 0, r["missile_rack"].get("missile_size"), kind


def weapons(v, sizes, racks):
    """Every gun on the ship's stock loadout, grouped by who fires it, plus its missiles:
    {"guns": [[who, mount, how many mounts, [[count, size, gun]] per mount, DPS of the whole row]],
     "pilotDps", "missiles": [[count, size, kind]], "missileCount"}.
    who is pilot (their own guns, and turrets they can slave to their trigger), gunner (crewed and remote turrets) or
    auto (point defence). An empty turret has no guns. The wiki's own pilot DPS isn't used: on some ships (Polaris) it
    counts a crewed turret. None when the wiki has no weapon data for the ship."""
    w, t = v.get("weaponry"), v.get("turrets") or {}
    if not w:
        return None

    def kit(guns, fallback=()):
        """[[count, size, name]], most first; sizes from the gun list, else the mount's."""
        out = {}
        for i, g in enumerate(guns):
            size = sizes.get(g.get("name")) or (fallback[i] if i < len(fallback) else None)
            out[(size, g.get("name") or "?")] = out.get((size, g.get("name") or "?"), 0) + 1
        return [[n, size, name] for (size, name), n in sorted(out.items(), key=lambda x: (-(x[0][0] or 0), x[0][1]))]

    rows = {}
    fixed = (w.get("fixed_weapons") or {}).get("weapons") or []
    if fixed:
        rows[("pilot", "hardpoints", "")] = [1, kit(fixed), sum(g.get("dps") or 0 for g in fixed)]
    for mount in ("manned", "remote", "pdc"):
        for x in t.get(mount) or []:
            guns = x.get("weapons") or []
            if not guns and not x.get("weapon_sizes"):
                continue  # a camera or tractor mount, nothing to fire
            who = "auto" if mount == "pdc" else "pilot" if x.get("is_pilot_slaveable") else "gunner"
            each = kit(guns, x.get("weapon_sizes") or [])
            if not guns:
                each = [[len(x["weapon_sizes"]), max(x["weapon_sizes"]), ""]]  # empty mount
            key = (who, mount, json.dumps(each))
            row = rows.setdefault(key, [0, each, 0])
            row[0] += 1
            row[2] += x.get("dps_total") or sum(g.get("dps") or 0 for g in guns)
    order = {"pilot": 0, "gunner": 1, "auto": 2}
    guns = [[who, mount, n, each, round(dps)] for (who, mount, _), (n, each, dps) in rows.items()]
    guns.sort(key=lambda r: (order[r[0]], r[1] != "hardpoints", -max((g[1] or 0) for g in r[3])))
    missiles = {}
    for p in v.get("ports") or []:
        rack = racks.get(p.get("equipped_item_uuid")) if p.get("category_label") == "Missile & Bomb Racks" else None
        if rack and rack[0]:
            missiles[rack[1:]] = missiles.get(rack[1:], 0) + rack[0]
    return {"guns": guns, "pilotDps": round(sum(r[4] for r in guns if r[0] == "pilot")),
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
