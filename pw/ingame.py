"""In-game side of each ship, refreshed once a day.

- Star Citizen Wiki API (api.star-citizen.wiki, content CC BY-SA 4.0): insurance claim and expedite times and the
  expedite cost in aUEC (from the game files, with the game version), and the ship's pledge store history (every
  edition and price the wiki has seen, with dates). Its vehicle id is the Ship Matrix id.
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
        wiki, page = [], 1
        while True:
            d = _get(WIKI.format(page))
            # Each vehicle has ~77 fields (~60 KB); keep the few we use so a refresh stays well inside the memory cap.
            wiki += [{k: v.get(k) for k in KEEP} for v in d["data"]]
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
        db.executemany("INSERT OR REPLACE INTO ingame VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        db.execute("INSERT INTO state (key, value) VALUES ('ingame_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now),))
    log.info("in-game data: %d ships from the wiki, %d buy and %d rent prices", len(rows), len(buys), len(rents))


def build_rows(wiki, vehicles, buys, rents):
    """One row per Ship Matrix id: (mid, uuid, claim min, expedite min, expedite aUEC, version, history, buy, rent,
    wiki name). Several wiki entries can share an id (variants): insurance comes from the one with data, and prices
    and history are merged across all of them. UEX is matched by game UUID, or by name when UEX has no UUID."""
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
                    main.get("name") or ""))
    return out


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
