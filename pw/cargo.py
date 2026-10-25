"""Cargo grids from sc-cargo.space (github.com/sccargospace/sc-cargo.space, MIT licence), one JSON file per ship.

Checked once a day; the files are only downloaded again when the repo has changed. Each grid is stored as compact
boxes [x, z, y, width, length, height] in SCU units, laid out on the floor plan the way sc-cargo.space draws them.
"""
import json
import logging
import re
import time
import urllib.request

from .commands import norm
from .store import USER_AGENT

log = logging.getLogger("pledgewatch")

REPO = "sccargospace/sc-cargo.space"
TREE = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
VIEWER = "https://sc-cargo.space/#/viewer/"
REFRESH = 86400


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def refresh(db, now=None, force=False):
    now = int(now or time.time())
    last = db.execute("SELECT value FROM state WHERE key='cargo_at'").fetchone()
    if not force and last and now - json.loads(last[0]) < REFRESH:
        return
    try:
        tree = _get(TREE)
        sha = tree["sha"]
        old = db.execute("SELECT value FROM state WHERE key='cargo_sha'").fetchone()
        if force or not old or json.loads(old[0]) != sha:
            files = [t["path"] for t in tree["tree"] if t["path"].startswith("src/grids/") and t["path"].endswith(".json")]
            rows = [r for r in (parse(_get(RAW + f), f) for f in files) if r]
            with db:
                db.execute("DELETE FROM cargo")
                db.executemany("INSERT OR REPLACE INTO cargo VALUES (?,?,?,?,?,?,?)", rows)
                _state(db, "cargo_sha", sha)
            log.info("cargo grids: %d ships", len(rows))
        _state(db, "cargo_at", now)
    except Exception as e:
        log.warning("couldn't refresh cargo grids: %s", e)


def _state(db, key, value):
    with db:
        db.execute("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))


def parse(d, path=""):
    """(key, name, names json, scu, unofficial scu, boxes json, viewer url) for one grid file, or None."""
    official = d.get("official") or {}
    if not d.get("name") or not official.get("groups"):
        return None
    boxes = []
    for g in official["groups"]:
        gx, gz = g.get("x", 0), g.get("z", 0)
        for b in g.get("grids", []):
            boxes.append([gx + b.get("x", 0), gz + b.get("z", 0), b.get("y", 0),
                          b.get("width", 1), b.get("length", 1), b.get("height", 1)])
    names = [d["name"]] + list(d.get("alternativeNames") or [])
    scu = official.get("capacity") or sum(b[3] * b[4] * b[5] for b in boxes)
    extra = (d.get("unofficial") or {}).get("capacity")
    return (norm(d["name"]), d["name"], json.dumps([norm(n) for n in names]), scu, extra,
            json.dumps(boxes, separators=(",", ":")), VIEWER + d["name"].lower() + "-official")


def variants(name):
    """'Aurora CL (Mk I)' -> aurora cl mk i, aurora cl. 'Hull-D [Concept]' -> hull d."""
    plain = re.sub(r"\[[^\]]*\]", "", name)
    return {norm(plain), norm(re.sub(r"\([^)]*\)", "", plain))} - {""}


def lookup(db):
    """{normalised name: grid} covering every name, alternative name and their variants. Concept grids only fill
    in for ships that have no other grid."""
    out = {}
    rows = sorted(db.execute("SELECT * FROM cargo"), key=lambda r: "[" in r["name"])  # finished grids first
    for r in rows:
        grid = {"scu": r["scu"], "extra": r["extra"], "boxes": json.loads(r["boxes"]), "viewer": r["viewer"],
                "concept": "concept" in r["name"].lower()}
        for n in [r["name"]] + json.loads(r["names"]):
            for v in variants(n):
                out.setdefault(v, grid)
    return out


def find(grids, name):
    """The grid for a ship name: exact, else the longest grid name the ship's name starts with ('C8X Pisces
    Expedition' -> 'C8X Pisces'), else a grid whose name starts with the ship's ('Mercury' -> 'Mercury Star
    Runner') when there's only one."""
    key = norm(name)
    if key in grids:
        return grids[key]
    starts = [k for k in grids if key.startswith(k + " ")]
    if starts:
        return grids[max(starts, key=len)]
    longer = {id(grids[k]): grids[k] for k in grids if k.startswith(key + " ")}
    return next(iter(longer.values())) if len(longer) == 1 and len(key) >= 5 else None
