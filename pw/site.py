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
from . import release, whatsnew
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


def upgrade_label(title):
    """'BIS Warbond Edition' -> 'BIS Warbond', 'Aegis Reclaimer Best in Show Edition Upgrade' -> 'Best in Show'.
    One-off upgrades keep RSI's own name ('Anvil Carrack Upgrade'): they tend to apply from certain ships only."""
    if re.search(r"best in show", title, re.I):
        return "Best in Show"
    t = re.sub(r"\s*Edition\b", "", title).strip()
    return t or "Standard"


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
    # The upgrade (CCU) store: what each ship is worth as an upgrade (msrp, RSI's id for it) and the upgrades to it
    # on sale now. Ships with no Ship Matrix match (rare) are left out rather than added as bare entries.
    for u in db.execute("SELECT id, name, msrp FROM upgrade_ships"):
        ship = ships.get(match_key(matrix, u["name"]))
        if ship is not None and norm(ship["name"]) == norm(u["name"]):
            ship["ccu"] = {"ref": u["id"], "value": u["msrp"]}
    for u in db.execute("SELECT sku, name, title, price FROM upgrade_skus WHERE listed=1 ORDER BY price"):
        ship = ships.get(match_key(matrix, u["name"]))
        if ship is not None:
            ship.setdefault("upgrades", []).append({"sku": u["sku"], "label": upgrade_label(u["title"]),
                                                    "price": u["price"]})
    grids = cargo_grids.lookup(db)
    released = release.lookup(db)
    gold = release.gold(db)
    out = []
    for ship in ships.values():
        if released.get(ship["name"]) and ship["status"] in ("", "Flight ready"):
            ship["released"] = released[ship["name"]]
        if gold.get(ship["name"]):
            ship["gold"] = gold[ship["name"]]
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
    for e in db.execute("SELECT ts, kind, data FROM events WHERE kind NOT IN ('store_down', 'store_ok', 'upgrade') "
                        "ORDER BY id DESC LIMIT 150"):
        d = json.loads(e["data"])
        changes.append({"ts": e["ts"], "kind": e["kind"], "name": d.get("name"), "price": d.get("price"),
                        "was": d.get("was"), "now": d.get("now"), "limited": d.get("limited"), "url": d.get("url")})
    first = db.execute("SELECT MIN(first_seen) FROM ships").fetchone()[0]
    last_ok = db.execute("SELECT value FROM state WHERE key='last_ok'").fetchone()
    return {"ships": out, "changes": changes, "newest": whatsnew.NEWEST, "gameVersion": version, "trackingSince": first, "checkedAt": json.loads(last_ok[0]) if last_ok
            else None, "builtAt": now}


def plan(db):
    """The upgrade planner's map, kept small: every ship RSI's upgrade tool knows ([id, name, value]), the upgrade
    editions on sale ({sku: [ship id, label, upgrade value]}), and what each ship can upgrade into from the last
    map run ({from id: [[sku, cost], ...]}). Upgrades that have left the store since that run are dropped."""
    ships = [[r["id"], r["name"], r["msrp"]] for r in db.execute("SELECT id, name, msrp FROM upgrade_ships ORDER BY id")
             if r["msrp"]]
    skus = {r["sku"]: [r["ref"], upgrade_label(r["title"]), r["price"]]
            for r in db.execute("SELECT sku, ref, title, price FROM upgrade_skus WHERE listed=1 ORDER BY sku")}
    paths = {}
    for r in db.execute("SELECT from_ref, sku, cost FROM upgrade_paths ORDER BY from_ref, cost"):
        if r["sku"] in skus:
            paths.setdefault(str(r["from_ref"]), []).append([r["sku"], r["cost"]])
    at = db.execute("SELECT value FROM state WHERE key='paths_at'").fetchone()
    return {"at": json.loads(at[0]) if at else None, "ships": ships, "skus": skus, "paths": paths}


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
    if g["weapons"]:
        out["weapons"] = json.loads(g["weapons"])
    return out


def _crew(lo, hi):
    lo, hi = int(lo or 0), int(hi or 0)
    if not lo and not hi:
        return ""
    return str(lo or hi) if lo == hi or not hi else f"{lo}–{hi}"


def _img_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


COSTS_TTL = 600  # seconds an answer from RSI's upgrade tool is reused
SESSION_TTL = 1200  # RSI's guest upgrade session lasts 30 minutes
COSTS_TIMEOUT = 10  # seconds per RSI request, so one slow answer can't hold up everyone's lookups for long

# View channels, send messages, embed links, read history, mention roles (so role pings work even when the role
# isn't set to mentionable).
INVITE_PERMISSIONS = 216064

PRIVACY = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Privacy · Pledge Watch</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="color-scheme" content="light dark">
<style>body{max-width:42rem;margin:0 auto;padding:32px 16px;font:16px/1.6 system-ui,sans-serif}
h1{font-size:26px}h2{font-size:18px;margin-top:28px}a{color:#b26b00}code{font-size:14px}</style></head><body>
<p><a href="/">← Pledge Watch</a></p>
<h1>Privacy</h1>
<p>Pledge Watch is a fan project that tracks the public RSI pledge store. It has no accounts, sets no cookies and runs no
analytics on this website.</p>
<h2>The website</h2>
<p>Pages are served through Cloudflare, which sees visitors' IP addresses to deliver and protect the site, as any
Cloudflare site does. Pledge Watch itself keeps no visitor logs. Your "aUEC an hour" figure is stored only in your own
browser. When you pick a ship under "I own", the site asks RSI's public upgrade tool what that ship can upgrade
into; RSI sees Pledge Watch's request, never yours, and nothing about you is sent or kept. Upgrades you list on the
upgrade planner as ones you already have are stored only in your own browser too.</p>
<h2>The Discord and Fluxer bot</h2>
<p>It stores only what it needs to work:</p>
<ul>
<li>For each server that runs <code>/alerts setup</code>: the server, channel and (optional) role IDs.</li>
<li>For each <code>/watch</code>: your user ID, the ship name or price you typed, and which server you ran it in.</li>
</ul>
<p>It doesn't read messages in your server (Discord doesn't send it any, and on Fluxer it only answers commands that
start with <code>!</code> in its own channel), and it never stores message content, names or avatars.</p>
<h2>Deleting your data</h2>
<ul>
<li><code>/unwatch all</code> deletes all your watches.</li>
<li><code>/alerts off</code> stops alerts in a server; removing the bot from a server deletes that server's settings
and every watch made in it.</li>
</ul>
<p>Nothing is sold or shared. See also the <a href="/terms">terms</a>. Questions: message the owner in the InPints
Discord.</p>
</body></html>"""


TERMS = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Terms · Pledge Watch</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="color-scheme" content="light dark">
<style>body{max-width:42rem;margin:0 auto;padding:32px 16px;font:16px/1.6 system-ui,sans-serif}
h1{font-size:26px}h2{font-size:18px;margin-top:28px}a{color:#b26b00}code{font-size:14px}</style></head><body>
<p><a href="/">← Pledge Watch</a></p>
<h1>Terms of Service</h1>
<p>Pledge Watch (this website and its Discord and Fluxer bot) is a free fan project. By using it you agree to these
terms. Last updated October 25, 2026.</p>
<h2>Unofficial</h2>
<p>Pledge Watch is not affiliated with, endorsed by or connected to Cloud Imperium Games or Roberts Space Industries.
Star Citizen, ship names and images belong to their owners.</p>
<h2>No guarantees</h2>
<p>Prices, stock, insurance, in-game prices and other details come from public sources (the RSI pledge store, RSI's
Ship Matrix and Loaner Ship Matrix, UEX, the Star Citizen Wiki and sc-cargo.space). They can be wrong, incomplete or
late, and alerts can be delayed or missed. <strong>Always check the RSI store before you buy.</strong> The service is
provided as is, without warranty of any kind, and may change, pause or stop at any time.</p>
<h2>Using the bot</h2>
<ul>
<li>Server admins choose where alerts go with <code>/alerts setup</code> and can stop them with <code>/alerts off</code>
or by removing the bot.</li>
<li>Don't use Pledge Watch to spam, harass or break Discord's, Fluxer's or RSI's rules, and don't try to overload or
break the service.</li>
<li>The bot may leave servers, for example when it's at its server limit or a server misuses it.</li>
</ul>
<h2>Liability</h2>
<p>To the extent the law allows, the people running Pledge Watch aren't liable for any loss that comes from using it or
relying on its information, including pledges bought or missed.</p>
<h2>Privacy</h2>
<p>What the bot stores and how to delete it is on the <a href="/privacy">privacy page</a>.</p>
<h2>Changes</h2>
<p>These terms may be updated; the date above shows the latest version. Questions: message the owner in the InPints
Discord.</p>
</body></html>"""


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
        self.plan = self.plan_gz = b""
        self.plan_etag = ""
        self.costs = {}  # upgrade ship id -> (fetched at, {sku: cost})
        self.costs_lock = asyncio.Lock()
        self.upgrade_session = None  # (made at, upgrades.Session)

    def refresh(self):
        """Rebuild the page from the database. Called at start and after every store check."""
        data = build(self.db)
        app_id = os.environ.get("DISCORD_APP_ID", "")
        from .servers import MAX_SERVERS
        count = self.db.execute("SELECT value FROM state WHERE key='discord_servers'").fetchone()
        others = (json.loads(count[0]) if count else 0) - (1 if os.environ.get("DISCORD_GUILD_ID") else 0)
        data["inviteFull"] = others >= MAX_SERVERS
        if app_id:
            data["invite"] = (f"https://discord.com/oauth2/authorize?client_id={app_id}&permissions={INVITE_PERMISSIONS}"
                              "&integration_type=0&scope=bot+applications.commands")
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
        self.plan = json.dumps(plan(self.db), separators=(",", ":")).encode()
        self.plan_gz = gzip.compress(self.plan, 9)
        self.plan_etag = '"' + hashlib.sha1(self.plan).hexdigest()[:16] + '"'

    def _send(self, request, body, gz, ctype, etag=None):
        etag = etag or self.etag
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        headers = {"Content-Type": ctype,
                   "Cache-Control": "public, max-age=60, stale-while-revalidate=600, stale-if-error=86400",
                   "ETag": etag, "Vary": "Accept-Encoding"}
        if "gzip" in request.headers.get("Accept-Encoding", ""):
            headers["Content-Encoding"] = "gzip"
            body = gz
        return web.Response(body=body, headers=headers)

    async def index(self, request):
        return self._send(request, self.page, self.page_gz, "text/html; charset=utf-8")

    async def ships_json(self, request):
        return self._send(request, self.api, self.api_gz, "application/json")

    async def plan_json(self, request):
        return self._send(request, self.plan, self.plan_gz, "application/json", self.plan_etag)

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

    def _file(self, name):
        async def handler(request):
            return web.FileResponse(os.path.join(self.dist, name), headers={"Cache-Control": "public, max-age=604800"})
        return handler

    async def upgrade_costs(self, request):
        """What one ship can upgrade into right now and what each costs from it, straight from RSI's upgrade tool.
        Kept for COSTS_TTL, and one RSI request at a time, so busy moments can't turn into a flood of requests."""
        ref = int(request.match_info["ref"])
        if not self.db.execute("SELECT 1 FROM upgrade_ships WHERE id=?", (ref,)).fetchone():
            raise web.HTTPNotFound()
        async with self.costs_lock:
            hit = self.costs.get(ref)
            if not hit or time.time() - hit[0] > COSTS_TTL:
                try:
                    hit = self.costs[ref] = (time.time(), await asyncio.to_thread(self._fetch_costs, ref))
                except Exception as e:
                    log.warning("upgrade costs for %s: %s", ref, e)
                    self.upgrade_session = None
                    if not hit:
                        raise web.HTTPBadGateway()
        body = json.dumps({"ref": ref, "at": int(hit[0]), "costs": hit[1]}, separators=(",", ":"))
        return web.Response(text=body, content_type="application/json",
                            headers={"Cache-Control": f"public, max-age={COSTS_TTL // 2}"})

    def _fetch_costs(self, ref):
        from .upgrades import Session
        if not self.upgrade_session or time.time() - self.upgrade_session[0] > SESSION_TTL:
            self.upgrade_session = (time.time(), Session(timeout=COSTS_TIMEOUT))
        return self.upgrade_session[1].costs(ref)

    async def privacy(self, request):
        return web.Response(text=PRIVACY, content_type="text/html", headers={"Cache-Control": "public, max-age=3600"})

    async def whats_new(self, request):
        return web.Response(text=whatsnew.page(), content_type="text/html", headers={"Cache-Control": "public, max-age=600"})

    async def terms(self, request):
        return web.Response(text=TERMS, content_type="text/html", headers={"Cache-Control": "public, max-age=3600"})

    async def health(self, request):
        return web.Response(text="ok")

    def app(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/plan", self.index)  # the same page; it shows the planner at this address
        app.router.add_get("/plan.json", self.plan_json)
        app.router.add_get("/ships.json", self.ships_json)
        app.router.add_get("/img/{id:[0-9a-f]{16}}.jpg", self.image)
        app.router.add_get("/upgrades/{ref:[0-9]{1,6}}.json", self.upgrade_costs)
        app.router.add_get("/healthz", self.health)
        app.router.add_get("/privacy", self.privacy)
        app.router.add_get("/terms", self.terms)
        app.router.add_get("/whats-new", self.whats_new)
        for name in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
            app.router.add_get(f"/{name}", self._file(name))
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


async def serve(site, port, host="0.0.0.0"):
    runner = web.AppRunner(site.app(), access_log=None)
    await runner.setup()
    # reuse_port lets a new copy start listening before the old one stops, so a deploy never leaves a gap.
    await web.TCPSite(runner, host, port, reuse_port=True).start()
    log.info("site on :%d", port)
