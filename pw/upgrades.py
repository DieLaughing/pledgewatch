"""Read RSI's ship upgrade (CCU) store and log upgrades that come in, come back or get cheaper.

A CCU turns a ship you own into a pricier one for the difference. The upgrade tool's API answers logged-out visitors:
after the store page hands out its guest Rsi-Token, two calls set up a guest upgrade session (cookies), and then
- `ships` lists every ship with the upgrade editions on sale now (standard, warbond, ...) and their target prices, and
- `to(from: ship)` lists exactly what one ship can upgrade into, with what each upgrade costs from it. Warbond
  editions often only apply from some ships, so the cost comes from here, not from subtracting prices.

Every few hours `map_paths` asks `to(from)` for every ship, which gives the upgrade planner its map.
"""
import json
import logging
import time
import urllib.request

from . import db as store_db
from .store import BASE, STORE_PAGE, StoreError, _opener

log = logging.getLogger("pledgewatch")

API = BASE + "/pledge-store/api/upgrade/graphql"
PAGE = BASE + "/en/account/pledges"  # My Hangar: RSI's Ship Upgrade tool opens from here (logged in)
# If a check finds far fewer upgrade editions than we have listed, treat it as a bad read.
MIN_SHARE = 0.5
MAP_EVERY = 3 * 3600  # seconds between planner map runs
MAP_PAUSE = 0.5  # seconds between ships, so a run is a slow trickle (about 3 minutes for 240 ships)
MAP_RETRY = 1800  # after a failed run
# A run that hears back about fewer ships than this is dropped; the previous map stays.
MAP_MIN_SHARE = 0.9
SESSION_TTL = 1200  # RSI's guest upgrade session lasts 30 minutes

SHIPS = """query initShipUpgrade { ships { id name msrp medias { productThumbMediumAndSmall }
  skus { id title price available } } }"""
TARGETS = """query filterShips($fromId: Int, $toFilters: [FilterConstraintValues]) {
  to(from: $fromId, filters: $toFilters) { ships { id skus { id upgradePrice } } } }"""


class Session:
    def __init__(self, timeout=30):
        self.opener, jar = _opener()
        self.timeout = timeout
        self.opener.open(STORE_PAGE, timeout=timeout).read()
        self.token = next((c.value for c in jar if c.name == "Rsi-Token"), None)
        if not self.token:
            raise StoreError("store page gave no Rsi-Token cookie")
        for path in ("/api/account/v2/setAuthToken", "/api/ship-upgrades/setContextToken"):
            if not self._post(BASE + path, {}).get("success"):
                raise StoreError(f"upgrade session: {path} refused")

    def _post(self, url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-rsi-token": self.token})
        return json.load(self.opener.open(req, timeout=self.timeout))

    def query(self, name, query, variables=None):
        reply = self._post(API, [{"operationName": name, "query": query, "variables": variables or {}}])[0]
        if reply.get("errors"):
            raise StoreError("upgrade store said: " + "; ".join(e.get("message", "?") for e in reply["errors"]))
        return reply["data"]

    def ships(self):
        return [{"id": s["id"], "name": " ".join(s["name"].split()), "msrp": s["msrp"],
                 "image": ((s.get("medias") or {}).get("productThumbMediumAndSmall") or ""),
                 "skus": [{"id": k["id"], "title": " ".join(k["title"].split()), "price": k["price"]}
                          for k in s["skus"] or [] if k.get("available", True)]}
                for s in self.query("initShipUpgrade", SHIPS)["ships"]]

    def costs(self, from_id):
        """{sku id: upgrade cost in cents} for every upgrade edition `from_id` can take right now."""
        data = self.query("filterShips", TARGETS, {"fromId": from_id, "toFilters": []})
        return {k["id"]: k["upgradePrice"] for s in data["to"]["ships"] for k in s["skus"] if k.get("upgradePrice")}


def buyable(title):
    """Subscriber editions show up for guests but only subscribers can buy them."""
    return "subscriber" not in title.lower()


def check(db, ships=None, costs=None, now=None):
    """Read the upgrade store, save it, and return events for upgrades that came in, came back or got cheaper.
    `ships` and `costs` (from_id -> {sku: cost}) are for tests; normally they're fetched."""
    now = int(now or time.time())
    sess = None
    try:
        if ships is None:
            sess = Session()
            ships = sess.ships()
    except (StoreError, OSError, ValueError, KeyError) as e:
        log.warning("upgrade store check failed: %s", e)
        return []
    known = {r["sku"]: dict(r) for r in db.execute("SELECT * FROM upgrade_skus")}
    listed = sum(1 for r in known.values() if r["listed"])
    seen = {k["id"]: (s, k) for s in ships for k in s["skus"] if buyable(k["title"])}
    if listed and len(seen) < listed * MIN_SHARE:
        log.warning("upgrade store returned %d upgrades, expected about %d; skipped", len(seen), listed)
        return []

    events = []
    for sku, (s, k) in seen.items():
        old = known.get(sku)
        e = {"kind": "upgrade", "id": None, "sku": sku, "ref": s["id"], "name": s["name"], "title": k["title"],
             "price": k["price"], "msrp": s["msrp"], "image": s["image"], "url": PAGE}
        if old is None:
            events.append(e)
        elif not old["listed"]:
            events.append({**e, "back": True, "last_seen": old["last_seen"]})
        elif k["price"] < old["price"]:
            events.append({**e, "was": old["price"]})
    if not known:
        events = []  # the first look is the baseline

    refs = [r[0] for r in db.execute("SELECT DISTINCT ref FROM watches WHERE kind='from'")]
    if events and refs:
        costs = costs if costs is not None else _costs(sess, refs)
        for e in events:
            e["costs"] = {str(ref): c[e["sku"]] for ref, c in costs.items() if e["sku"] in c}

    with db:
        db.execute("DELETE FROM upgrade_ships")
        db.executemany("INSERT INTO upgrade_ships (id, name, msrp) VALUES (?,?,?)",
                       [(s["id"], s["name"], s["msrp"]) for s in ships])
        for sku, (s, k) in seen.items():
            db.execute("""INSERT INTO upgrade_skus (sku, ref, name, title, price, msrp, listed, first_seen, last_seen)
                          VALUES (?,?,?,?,?,?,1,?,?) ON CONFLICT(sku) DO UPDATE SET ref=excluded.ref,
                          name=excluded.name, title=excluded.title, price=excluded.price, msrp=excluded.msrp,
                          listed=1, last_seen=excluded.last_seen""",
                       (sku, s["id"], s["name"], k["title"], k["price"], s["msrp"], now, now))
        gone = [sku for sku, r in known.items() if r["listed"] and sku not in seen]
        db.executemany("UPDATE upgrade_skus SET listed=0 WHERE sku=?", [(g,) for g in gone])
    store_db.save(db, {}, events, now)
    return events


def _costs(sess, refs):
    out = {}
    for ref in refs:
        try:
            sess = sess or Session()
            out[ref] = sess.costs(ref)
        except (StoreError, OSError, ValueError, KeyError) as e:
            log.warning("upgrade costs from ship %s failed: %s", ref, e)
        time.sleep(1)
    return out


def map_paths(db, fetch=None, now=None):
    """Ask RSI what every ship can upgrade into and what each upgrade costs from it, and save that as the planner's
    map. Returns how many ships answered. Ships that didn't answer keep what the last run found; a run where too many
    didn't is dropped. `fetch` (ship id -> {sku: cost}) is for tests."""
    refs = [r[0] for r in db.execute("SELECT id FROM upgrade_ships ORDER BY id")]
    if not refs:
        return 0
    fetch = fetch or _fetcher()
    found = {}
    for ref in refs:
        try:
            found[ref] = fetch(ref)
        except (StoreError, OSError, ValueError, KeyError) as e:
            log.warning("upgrade map: ship %s failed: %s", ref, e)
    if len(found) < len(refs) * MAP_MIN_SHARE:
        log.warning("upgrade map: only %d of %d ships answered; kept the previous map", len(found), len(refs))
        return 0
    with db:
        db.executemany("DELETE FROM upgrade_paths WHERE from_ref=?", [(r,) for r in found])
        db.executemany("INSERT INTO upgrade_paths (from_ref, sku, cost) VALUES (?,?,?)",
                       [(r, sku, cost) for r, c in found.items() for sku, cost in c.items()])
    store_db.set_state(db, "paths_at", int(now or time.time()))
    log.info("upgrade map: %d ships, %d upgrades", len(found), sum(len(c) for c in found.values()))
    return len(found)


def _fetcher():
    """One guest session for the whole run, renewed when it's old or after an error."""
    sess = {"s": None, "at": 0}

    def fetch(ref):
        time.sleep(MAP_PAUSE)
        if not sess["s"] or time.time() - sess["at"] > SESSION_TTL:
            sess["s"], sess["at"] = Session(), time.time()
        try:
            return sess["s"].costs(ref)
        except (StoreError, OSError, ValueError, KeyError):
            sess["s"] = None
            raise
    return fetch


async def map_loop(path, after=None):
    """Run map_paths every MAP_EVERY seconds, counted from the last good run, so restarts don't trigger extra runs.
    Like the upgrade check, nothing that goes wrong here can stop the store checks, bots or website."""
    import asyncio
    db = store_db.connect(path, check_same_thread=False)  # only ever used by this loop, one step at a time
    while True:
        wait = (store_db.get_state(db, "paths_at", 0) or 0) + MAP_EVERY - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
            continue
        try:
            ok = await asyncio.to_thread(map_paths, db)
        except Exception:
            log.exception("upgrade map crashed")
            ok = 0
        if ok and after:
            after()
        if not ok:
            await asyncio.sleep(MAP_RETRY)
