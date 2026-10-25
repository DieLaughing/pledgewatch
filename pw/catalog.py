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
        return
    try:
        ships = [_ship(s) for s in _get(SHIP_MATRIX)["data"]]
        loaners = parse_loaners(_get(LOANERS)["article"]["body"])
    except Exception as e:
        log.warning("couldn't refresh the ship list: %s", e)
        return
    with db:
        db.execute("DELETE FROM catalog")
        db.executemany("INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)", ships)
        db.execute("DELETE FROM loaners")
        db.executemany("INSERT OR REPLACE INTO loaners VALUES (?,?,?)",
                       [(ship, json.dumps(keys), loan) for ship, keys, loan in loaners])
        db.execute("INSERT INTO state (key, value) VALUES ('catalog_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now),))
    log.info("ship list: %d ships, %d with loaners", len(ships), len(loaners))


def _ship(s):
    name = " ".join(s["name"].split())
    maker = (s.get("manufacturer") or {}).get("name", "")
    url = "https://robertsspaceindustries.com" + s["url"] if s.get("url", "").startswith("/") else ""
    return (name, norm(name), maker, s.get("production_status") or "", s.get("focus") or "", s.get("size") or "", url)


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


def info(db, name):
    """Status and loaners for a store ship name, or {} if we can't tell."""
    try:
        key = base_key(name)
        row = db.execute("SELECT status FROM catalog WHERE key=?", (key,)).fetchone()
        result = {"status": STATUS.get(row[0], row[0])} if row and row[0] else {}
        for ship, keys, loan in db.execute("SELECT ship, keys, loaners FROM loaners"):
            if any(_same(k, key) for k in json.loads(keys)):
                result["loaners"] = loan
                break
        return result
    except Exception:  # tables not there yet
        return {}
