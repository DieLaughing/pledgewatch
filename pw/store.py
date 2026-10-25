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
        ... on TyItem { price { amount discounted } stock { available show level unlimited } }
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


def _item(r, category):
    price = r.get("price") or {}
    stock = r.get("stock") or {}
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
    }
