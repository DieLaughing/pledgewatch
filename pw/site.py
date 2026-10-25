"""The website: one page with every ship and every way to buy it, plus the change log.

The page's data is put straight into the HTML, so a visit is one request and the list draws immediately. Ship pictures
are fetched from RSI once and served from here, so visitors' browsers never talk to RSI. No cookies, no accounts,
no analytics.
"""
import asyncio
import gzip
import hashlib
import json
import logging
import os
import re
import time
import urllib.request

from aiohttp import web

from . import cargo as cargo_grids
from .catalog import STATUS, info, match_key
from .commands import norm
from .store import USER_AGENT

log = logging.getLogger("pledgewatch")

EDITIONS = [("Warbond", re.compile(r"warbond", re.I)), ("10 Year", re.compile(r"\b10 year\b", re.I)),
            ("Best in Show", re.compile(r"best in show", re.I))]
EDITION_ORDER = {"Standard": 0, "Warbond": 1, "10 Year": 2, "Best in Show": 3}
SIZES = ["Vehicle", "Snub", "Small", "Medium", "Large", "Capital"]


def edition(name, url):
    for label, rx in EDITIONS:
        if rx.search(name) or rx.search(url.replace("-", " ")):
            return label
    return "Standard"


def build(db, now=None):
    """Everything the page shows, as one dict."""
    now = int(now or time.time())
    ships = {}
    by_id = {}
    game = {r["mid"]: r for r in db.execute("SELECT * FROM ingame")}
    version = ""
    for c in db.execute("SELECT * FROM catalog"):
        if c["mid"]:
            by_id[c["mid"]] = c["key"]
        ships[c["key"]] = {
            "key": c["key"], "name": c["name"], "maker": c["maker"], "makerCode": c["maker_code"],
            "role": c["focus"], "type": c["type"], "size": (c["size"] or "").title(),
            "crew": _crew(c["min_crew"], c["max_crew"]), "cargo": c["cargo"], "length": c["length"],
            "status": STATUS.get(c["status"], c["status"] or ""), "img": c["image"], "rsi": c["url"], "editions": [],
        }
        g = game.get(c["mid"])
        if g:
            ships[c["key"]].update(_game(g))
            version = max(version, g["version"] or "")
    matrix = set(ships)
    for s in db.execute("SELECT * FROM ships ORDER BY price"):
        key = (s["ship_id"] and by_id.get(s["ship_id"])) or match_key(matrix, s["name"])
        ship = ships.get(key)
        if ship is None:  # in the store but named differently in the Ship Matrix (e.g. PTV Buggy)
            ship = ships[key] = {"key": key, "name": re.sub(r"\s+-\s+.*$", "", s["name"]), "maker": "",
                                 "makerCode": "", "role": "", "type": "", "size": "", "crew": "", "cargo": None,
                                 "length": None, "status": "", "img": s["image"], "rsi": "", "editions": []}
        ed = "Warbond" if s["warbond"] else edition(s["name"], s["url"] or "")
        extras = json.loads(s["extras"] or "[]")
        ship["editions"].append({
            "label": ed, "price": s["price"], "listPrice": s["list_price"], "inStore": bool(s["listed"]),
            "available": bool(s["available"]), "limited": bool(s["limited"]), "level": s["level"] or "",
            "url": s["url"], "since": s["listed_since"], "lastSeen": s["last_seen"],
            "insurance": s["insurance"] or "", "paints": sum(1 for x in extras if "paint" in x.lower()),
            "includes": [x for x in extras if "hangar" not in x.lower()],
        })
        if not ship["img"]:
            ship["img"] = s["image"]
    grids = cargo_grids.lookup(db)
    out = []
    for ship in ships.values():
        g = cargo_grids.find(grids, ship["name"])
        if g:
            ship["grid"] = {"scu": g["scu"], "boxes": g["boxes"], "viewer": g["viewer"], "concept": g["concept"]}
            ship["cargo"] = g["scu"]
        ship["editions"].sort(key=lambda e: (not e["inStore"], EDITION_ORDER.get(e["label"], 9), e["price"] or 0))
        ship["inStore"] = any(e["inStore"] for e in ship["editions"])
        if ship["status"] and ship["status"] != "Flight ready":
            ship["loaners"] = info(db, ship["name"]).get("loaners", "")
        ship["img"] = f"/img/{_img_id(ship['img'])}.jpg" if ship["img"] else ""
        out.append(ship)
    out.sort(key=lambda s: norm(s["name"]))

    changes = []
    for e in db.execute("SELECT ts, kind, data FROM events WHERE kind NOT IN ('store_down', 'store_ok') "
                        "ORDER BY id DESC LIMIT 150"):
        d = json.loads(e["data"])
        changes.append({"ts": e["ts"], "kind": e["kind"], "name": d.get("name"), "price": d.get("price"),
                        "was": d.get("was"), "now": d.get("now"), "limited": d.get("limited"), "url": d.get("url")})
    first = db.execute("SELECT MIN(first_seen) FROM ships").fetchone()[0]
    last_ok = db.execute("SELECT value FROM state WHERE key='last_ok'").fetchone()
    return {"ships": out, "changes": changes, "gameVersion": version, "trackingSince": first, "checkedAt": json.loads(last_ok[0]) if last_ok
            else None, "builtAt": now}


def _game(g):
    """In-game prices, insurance and store history for one ship, trimmed for the page."""
    buy, rent = json.loads(g["buy"]), json.loads(g["rent"])
    out = {"history": [h[:4] for h in json.loads(g["history"])]}
    if g["claim"]:
        out["insurance"] = {"claim": round(g["claim"], 1), "expedite": round(g["expedite"] or 0, 1),
                            "expediteCost": int(g["expedite_cost"] or 0)}
    if buy:
        out["buy"] = [[int(p), t] for p, t, _ in buy]
    if rent:
        out["rent"] = [[int(p), t] for p, t, _ in rent]
    return out


def _crew(lo, hi):
    lo, hi = int(lo or 0), int(hi or 0)
    if not lo and not hi:
        return ""
    return str(lo or hi) if lo == hi or not hi else f"{lo}–{hi}"


def _img_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


class Site:
    def __init__(self, path, dist):
        from . import db as store_db
        self.db = store_db.connect(path)
        self.dist = dist
        self.img_dir = os.path.join(os.path.dirname(path), "img")
        os.makedirs(self.img_dir, exist_ok=True)
        self.page = self.page_gz = self.api = self.api_gz = b""
        self.images = {}
        self.etag = ""

    def refresh(self):
        """Rebuild the page from the database. Called at start and after every store check."""
        data = build(self.db)
        self.images = {}
        for c in self.db.execute("SELECT image FROM catalog UNION SELECT image FROM ships"):
            if c[0]:
                self.images[_img_id(c[0])] = c[0]
        blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
        template = open(os.path.join(self.dist, "index.html"), encoding="utf-8").read()
        html = template.replace("<!--DATA-->", f'<script id="data" type="application/json">{blob}</script>')
        self.page, self.api = html.encode(), blob.encode()
        self.page_gz, self.api_gz = gzip.compress(self.page, 9), gzip.compress(self.api, 9)
        self.etag = '"' + hashlib.sha1(self.page).hexdigest()[:16] + '"'

    def _send(self, request, body, gz, ctype):
        if request.headers.get("If-None-Match") == self.etag:
            return web.Response(status=304, headers={"ETag": self.etag})
        headers = {"Content-Type": ctype, "Cache-Control": "public, max-age=60, stale-while-revalidate=600",
                   "ETag": self.etag, "Vary": "Accept-Encoding"}
        if "gzip" in request.headers.get("Accept-Encoding", ""):
            headers["Content-Encoding"] = "gzip"
            body = gz
        return web.Response(body=body, headers=headers)

    async def index(self, request):
        return self._send(request, self.page, self.page_gz, "text/html; charset=utf-8")

    async def ships_json(self, request):
        return self._send(request, self.api, self.api_gz, "application/json")

    async def image(self, request):
        img = request.match_info["id"]
        src = self.images.get(img)
        if not src:
            raise web.HTTPNotFound()
        path = os.path.join(self.img_dir, img + ".jpg")
        if not os.path.exists(path):
            try:
                body = await asyncio.to_thread(_download, src)
            except Exception as e:
                log.warning("image %s: %s", src, e)
                raise web.HTTPBadGateway()
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
        return web.FileResponse(path, headers={"Cache-Control": "public, max-age=604800, immutable"})

    async def health(self, request):
        return web.Response(text="ok")

    def app(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/ships.json", self.ships_json)
        app.router.add_get("/img/{id:[0-9a-f]{16}}.jpg", self.image)
        app.router.add_get("/healthz", self.health)
        app.router.add_static("/assets", os.path.join(self.dist, "assets"), append_version=False)
        app.on_response_prepare.append(_security_headers)
        return app


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        if not r.headers.get("Content-Type", "").startswith("image/"):
            raise ValueError("not an image")
        return r.read(2_000_000)


async def _security_headers(request, response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")  # 180 days, this host only
    response.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    if request.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"


async def serve(site, port):
    runner = web.AppRunner(site.app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("site on :%d", port)
