"""Every ship that exists, not just what's on sale: RSI's Ship Matrix (names, maker, flight-ready or concept) and the
official Loaner Ship Matrix (what you fly until a ship is flight-ready). Refreshed once a day."""
import html
import json
import logging
import re
import time
import urllib.request

from .commands import norm
from .store import USER_AGENT

log = logging.getLogger("pledgewatch")

SHIP_MATRIX = "https://robertsspaceindustries.com/ship-matrix/index"
LOANERS = "https://support.robertsspaceindustries.com/api/v2/help_center/en-us/articles/360003093114.json"
REFRESH = 86400
# More changes than this in one day means RSI reworked a page, not news: log them for the site but don't post.
MAX_POSTED_CHANGES = 12

STATUS = {"flight-ready": "Flight ready", "in-concept": "In concept", "in-production": "In production"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def refresh(db, now=None, force=False):
    """Reload both lists if they're older than a day. A failure keeps the old copy."""
    now = int(now or time.time())
    last = db.execute("SELECT value FROM state WHERE key='catalog_at'").fetchone()
    if not force and last and now - json.loads(last[0]) < REFRESH:
        return []
    try:
        ships = [_ship(s) for s in _get(SHIP_MATRIX)["data"]]
        loaners = parse_loaners(_get(LOANERS)["article"]["body"])
    except Exception as e:
        log.warning("couldn't refresh the ship list: %s", e)
        return []
    events = apply(db, ships, loaners, now)
    log.info("ship list: %d ships, %d with loaners, %d change(s)", len(ships), len(loaners), len(events))
    return events


def apply(db, ships, loaners, now):
    """Replace both lists and log what changed since last time: a ship's flight status (In concept -> Flight
    ready) and the loaners RSI lists for it. The first load is a quiet baseline."""
    old_status = {r[0]: r[1] for r in db.execute("SELECT name, status FROM catalog")}
    old_loaners = {r[0]: r[1] for r in db.execute("SELECT ship, loaners FROM loaners")}
    events = []
    if old_status:
        for row in ships:
            name, status, url = row[0], row[4], row[13]
            was = old_status.get(name)
            if name not in old_status:
                events.append({"kind": "status", "name": name, "url": url, "was": "", "now": STATUS.get(status, status)})
            elif was != status:
                events.append({"kind": "status", "name": name, "url": url, "was": STATUS.get(was, was),
                               "now": STATUS.get(status, status)})
    if old_loaners:
        for ship, _, loan in loaners:
            if old_loaners.get(ship) != loan:
                events.append({"kind": "loaners", "name": ship, "url": "", "was": old_loaners.get(ship, ""),
                               "now": loan})
        for ship, loan in old_loaners.items():
            if ship not in {l[0] for l in loaners}:
                events.append({"kind": "loaners", "name": ship, "url": "", "was": loan, "now": ""})
    with db:
        db.execute("DELETE FROM catalog")
        db.executemany("INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ships)
        db.execute("DELETE FROM loaners")
        db.executemany("INSERT OR REPLACE INTO loaners VALUES (?,?,?)",
                       [(ship, json.dumps(keys), loan) for ship, keys, loan in loaners])
        db.execute("INSERT INTO state (key, value) VALUES ('catalog_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now),))
        quiet = json.dumps({"discord": "skipped", "fluxer": "skipped"}) if len(events) > MAX_POSTED_CHANGES else "{}"
        for e in events:
            db.execute("INSERT INTO events (ts, kind, ship_id, data, posted) VALUES (?,?,?,?,?)",
                       (now, e["kind"], None, json.dumps(e), quiet))
    if len(events) > MAX_POSTED_CHANGES:
        log.warning("%d ship list changes at once; logged on the site, not posted", len(events))
    return events


def _ship(s):
    name = " ".join(s["name"].split())
    maker = s.get("manufacturer") or {}
    url = "https://robertsspaceindustries.com" + s["url"] if s.get("url", "").startswith("/") else ""
    media = (s.get("media") or [{}])[0] or {}
    image = (media.get("images") or {}).get("store_small") or ""
    return (name, norm(name), maker.get("name", ""), maker.get("code", ""), s.get("production_status") or "",
            s.get("focus") or "", s.get("type") or "", s.get("size") or "", _num(s.get("min_crew")),
            _num(s.get("max_crew")), _num(s.get("cargocapacity")), _num(s.get("length")), image, url)


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_loaners(body):
    """Rows of (ship as written, [normalised names it covers], loaners) from the article's table."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2 or not cells[0] or cells[0].upper() == "YOUR SHIP":
            continue
        out.append((cells[0], _covers(cells[0]), cells[1]))
    return out


def _covers(ship):
    """'600i Explorer and Executive' covers '600i explorer' and '600i executive'."""
    parts = [p for p in re.split(r"\s*(?:,|/|&|\band\b)\s*", ship) if p.strip()]
    first = norm(parts[0]).split()[0] if parts else ""
    keys = []
    for p in parts:
        k = norm(re.sub(r"\bvariants?\b", "", p, flags=re.I))  # "G12 Variants" covers G12, G12r, G12a
        if keys and first and not k.startswith(first):
            k = f"{first} {k}"
        keys.append(k)
    return keys


def _same(loaner_key, key):
    """Loaner names are looser than the Ship Matrix: 'g12' covers 'g12r', 'genesis starliner' means 'genesis'."""
    a, b = loaner_key, key
    return a == b or b.startswith(a + " ") or a.startswith(b + " ") or (len(a) >= 3 and b.startswith(a) and
                                                                        b[len(a):].isalpha() and len(b) - len(a) <= 2)


def base_key(name):
    """Store names carry edition suffixes the Ship Matrix doesn't: 'Constellation Mk V Centaurus - 10 Year'."""
    name = re.sub(r"\s+-\s+(\d+ Year|Warbond|Best In Show.*)$", "", name, flags=re.I)
    return norm(name)


def match_key(keys, name):
    """The Ship Matrix key for a store name. Falls back to the longest matrix name the store name starts with, so
    'PTV Buggy' finds 'PTV' and 'Ursa Rover' finds 'Ursa'."""
    key = base_key(name)
    if key in keys:
        return key
    starts = [k for k in keys if key.startswith(k + " ")]
    return max(starts, key=len) if starts else key


def info(db, name):
    """Status and loaners for a store ship name, or {} if we can't tell."""
    try:
        key = match_key({r[0] for r in db.execute("SELECT key FROM catalog")}, name)
        row = db.execute("SELECT status FROM catalog WHERE key=?", (key,)).fetchone()
        result = {"status": STATUS.get(row[0], row[0])} if row and row[0] else {}
        for ship, keys, loan in db.execute("SELECT ship, keys, loaners FROM loaners"):
            if any(_same(k, key) for k in json.loads(keys)):
                result["loaners"] = loan
                break
        return result
    except Exception:  # tables not there yet
        return {}
