"""When each ship became flyable: the game patch it was added in, from the Star Citizen Wiki's ship pages
(infobox field `addedinversion`, e.g. "Alpha 4.8.0"). Concept ships carry placeholders ("Alpha 4.x.x") and get none.
Refreshed once a day, 50 pages per request.

Also which ships have had a "gold standard" pass (reworked to every vehicle feature the game has so far), from the
table on the wiki's Vehicle Pipeline page. CIG doesn't publish a list; the wiki keeps this one by hand.
"""
import json
import logging
import re
import time
import urllib.parse
import urllib.request

from .commands import norm
from .store import USER_AGENT

log = logging.getLogger("pledgewatch")

API = ("https://starcitizen.tools/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json"
       "&redirects=1&titles=")
PIPELINE = "Vehicle_Pipeline"
REFRESH = 86400
FIELD = re.compile(r"^\|\s*addedinversion\s*=\s*(.*?)\s*$", re.M)
VERSION = re.compile(r"^(?:Alpha|Patch)?\s*V?(\d+(?:\.\d+){1,3})[a-z]?$", re.I)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def patch_of(wikitext):
    """'Alpha 3.24.3' -> '3.24.3', 'Patch V0.9.2.1' -> '0.9.2.1', 'Alpha 3.20.0b' -> '3.20.0'. The hangar module came
    before any patch ('0'). Placeholders on concept ships ('Alpha 4.x.x') -> ''."""
    m = FIELD.search(wikitext or "")
    value = re.sub(r"<[^>]+>.*$|\{\{.*$", "", m.group(1)).strip() if m else ""
    if value.lower() == "hangar module":
        return "0"
    v = VERSION.match(value)
    return v.group(1) if v else ""


def key(patch):
    """Sortable form: '3.24.3' -> (3, 24, 3); '' sorts first (unknown)."""
    return tuple(int(p) for p in patch.split(".")) if patch else ()


def refresh(db, now=None, force=False):
    now = int(now or time.time())
    last = db.execute("SELECT value FROM state WHERE key='release_at'").fetchone()
    if not force and last and now - json.loads(last[0]) < REFRESH and db.execute("SELECT 1 FROM gold").fetchone():
        return
    names = [r[0] for r in db.execute("SELECT name FROM catalog")]
    if not names:
        return
    found = {}
    try:
        for i in range(0, len(names), 50):
            r = _get(API + urllib.parse.quote("|".join(names[i:i + 50])))["query"]
            back = {}
            for step in ("normalized", "redirects"):
                for x in r.get(step, []):
                    back[x["to"]] = back.get(x["from"], x["from"])
            for page in r.get("pages", {}).values():
                text = ((page.get("revisions") or [{}])[0].get("slots") or {}).get("main", {}).get("*", "")
                title = page.get("title", "")
                found[back.get(title, title)] = patch_of(text)
            time.sleep(1)
    except Exception as e:
        log.warning("couldn't refresh release patches: %s", e)
        return
    with db:
        db.execute("DELETE FROM released")
        db.executemany("INSERT INTO released VALUES (?,?)", [(n, p) for n, p in found.items() if p])
        db.execute("INSERT INTO state (key, value) VALUES ('release_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(now),))
    log.info("release patches: %d ships", sum(1 for p in found.values() if p))
    try:
        page = next(iter(_get(API + PIPELINE)["query"]["pages"].values()))
        gold = gold_rows(page["revisions"][0]["slots"]["main"]["*"])
    except Exception as e:
        log.warning("couldn't refresh gold standard ships: %s", e)
        return
    if gold:  # an empty table means the page changed shape; keep the last good list
        with db:
            db.execute("DELETE FROM gold")
            db.executemany("INSERT OR REPLACE INTO gold VALUES (?,?,?)", gold)
        log.info("gold standard: %d ships", len(gold))


LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")


def gold_rows(wikitext):
    """[(name, 'done' or 'in progress', patch)] from the 'List of gold standard vehicles' table. A row's name is the
    link's label, which can be a whole family ('Aurora Mk I', 'Cutlass')."""
    start = (wikitext or "").find("List of gold standard vehicles")
    if start < 0:
        return []
    table = wikitext[start:wikitext.find("|}", start)]
    out = []
    for row in table.split("\n|-")[1:]:
        cells = [c.strip() for c in row.strip().lstrip("|").split("||")]
        if len(cells) < 4:
            continue
        name = LINK.search(cells[0])
        patch = VERSION.match(re.sub(r"\{\{Alpha\|([^}]*)\}\}", r"\1", cells[3]).strip())
        if name:
            status = "done" if cells[2].lower() == "implemented" else "in progress"
            out.append((name.group(1).strip(), status, patch.group(1) if patch and status == "done" else ""))
    return out


def gold(db):
    """{ship name: {"status", "patch", "family"}}: each ship gets the most specific row whose words all appear in its
    name ('Sabre Raven EX' -> Sabre Raven, 'Sabre Comet' -> Sabre). `family` is that row's name when it isn't the
    ship's own, so the page can say the pass was for the family."""
    rows = {n: (st, p) for n, st, p in db.execute("SELECT name, status, patch FROM gold")}
    words = {n: set(norm(n).split()) - {"starlifter"} for n in rows}  # the wiki's 'A2 Hercules Starlifter'
    out = {}
    for (name,) in db.execute("SELECT name FROM catalog"):
        mine = set(norm(name).split())
        hits = [n for n, w in words.items() if w and w <= mine]
        if hits:
            n = max(hits, key=lambda n: len(words[n]))
            out[name] = {"status": rows[n][0], "patch": rows[n][1], "family": "" if words[n] == mine else n}
    return out


def lookup(db):
    """{ship name: patch}, filling gaps from the ship a variant is named after ('Carrack w/C8X' -> Carrack,
    'Mustang Alpha Vindicator' -> Mustang Alpha): the longest known name whose words all appear in it."""
    have = {r[0]: r[1] for r in db.execute("SELECT name, patch FROM released")}
    words = {n: set(norm(n).split()) for n in have}
    out = dict(have)
    for (name,) in db.execute("SELECT name FROM catalog WHERE status='flight-ready'"):
        if name in out:
            continue
        mine = set(norm(name).split())
        base = [n for n, w in words.items() if w and w <= mine]
        if base:
            out[name] = have[max(base, key=lambda n: len(words[n]))]
    return out
