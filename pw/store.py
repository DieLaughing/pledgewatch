"""Read the RSI pledge store.

The store page loads its listing from RSI's GraphQL endpoint. No login is needed: loading the store page hands out a
guest Rsi-Token cookie, which the endpoint accepts as the x-rsi-token header.
"""
import json
import urllib.request
from http.cookiejar import CookieJar

BASE = "https://robertsspaceindustries.com"
STORE_PAGE = BASE + "/en/pledge/ships"
GRAPHQL = BASE + "/graphql"
USER_AGENT = "PledgeWatch/0.1 (store change alerts; checks every few minutes)"

# Store categories to watch. 72 = Standalone Ships.
CATEGORIES = {"72": "Standalone Ships"}

QUERY = """query GetBrowseListingQuery($query: SearchQuery) {
  store(browse: true) {
    listing: search(query: $query) {
      resources {
        id name url
        media { thumbnail { storeSmall } }
        ... on TyItem { price { amount discounted } stock { available show level unlimited qty backOrder } }
        ... on TySku { isWarbond gameItems { name kind ... on ShipGameItem { shipId } } }
      }
      totalCount
    }
  }
}"""


class StoreError(Exception):
    pass


def _opener():
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener, jar


def fetch(timeout=30):
    """Return every listed item in CATEGORIES as a list of plain dicts. Raises StoreError if the store can't be read."""
    opener, jar = _opener()
    try:
        opener.open(STORE_PAGE, timeout=timeout).read()
        token = next((c.value for c in jar if c.name == "Rsi-Token"), None)
        if not token:
            raise StoreError("store page gave no Rsi-Token cookie")
        items = []
        for product, category in CATEGORIES.items():
            items += [_item(r, category) for r in _listing(opener, token, product, timeout)]
        return items
    except StoreError:
        raise
    except Exception as e:
        raise StoreError(f"{type(e).__name__}: {e}") from e


def _listing(opener, token, product, timeout, page_size=100):
    resources, page = [], 1
    while True:
        body = [{"operationName": "GetBrowseListingQuery", "query": QUERY,
                 "variables": {"query": {"skus": {"products": [product]}, "limit": page_size, "page": page}}}]
        req = urllib.request.Request(GRAPHQL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-rsi-token": token})
        reply = json.load(opener.open(req, timeout=timeout))[0]
        if reply.get("errors"):
            raise StoreError("store said: " + "; ".join(e.get("message", "?") for e in reply["errors"]))
        listing = reply["data"]["store"]["listing"]
        resources += listing["resources"]
        if len(resources) >= listing["totalCount"] or not listing["resources"]:
            return resources
        page += 1


INSURANCE = {"lifetime": "Lifetime", "120 month": "10 years", "6 month": "6 months"}


def insurance(text):
    """'120 Month Insurance' -> '10 years', '6 Month Insurance' -> '6 months', 'Lifetime Insurance' -> 'Lifetime'."""
    t = text.lower()
    for key, label in INSURANCE.items():
        if key in t:
            return label
    m = __import__("re").search(r"(\d+)\s*month", t)
    if m:
        n = int(m.group(1))
        return f"{n // 12} years" if n % 12 == 0 and n >= 24 else f"{n} months"
    return text.replace(" Insurance", "")


def _item(r, category):
    price = r.get("price") or {}
    stock = r.get("stock") or {}
    items = r.get("gameItems") or []
    ins = next((insurance(g["name"]) for g in items if g.get("kind") == "INSURANCE" and g.get("name")), "")
    ship_ids = [str(g["shipId"]) for g in items if g.get("kind") == "SHIP" and g.get("shipId")]
    extras = [g["name"] for g in items if g.get("kind") in ("SKIN", "CUSTOMIZATION", "HANGARPASS") and g.get("name")]
    amount = price.get("discounted") or price.get("amount")
    return {
        "id": str(r["id"]),
        "name": " ".join(r["name"].split()),
        "url": BASE + "/en" + r["url"] if r.get("url", "").startswith("/") else r.get("url", ""),
        "image": ((r.get("media") or {}).get("thumbnail") or {}).get("storeSmall") or "",
        "category": category,
        "price": amount,  # US cents, before tax
        "list_price": price.get("amount"),
        "available": bool(stock.get("available", True)),
        "limited": not stock.get("unlimited", True),
        "level": stock.get("level") or "",
        "qty": stock.get("qty"),  # undocumented; 0 for unlimited ships. Recorded to learn what it means for limited ones
        "warbond": bool(r.get("isWarbond")),
        "insurance": ins,
        "ship_id": ship_ids[0] if len(ship_ids) == 1 else "",  # Ship Matrix id; packs with several ships get none
        "extras": extras,
    }
