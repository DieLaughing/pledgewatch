"""Turn two looks at the store into a list of changes. No I/O here, so it's easy to test."""

# A ship has to be missing this many checks in a row before we call it gone, so one bad read doesn't cause a false
# "left the store" followed by a false "back".
MISSES_BEFORE_GONE = 2

# Stock levels RSI reports, most to least.
LEVELS = ["high", "medium", "low"]


def diff(known, seen):
    """Compare what we knew with what the store shows now.

    known: {id: ship row} from the database, including ships that have left (listed=False).
    seen:  {id: item} from this check.
    Returns (events, updates). events: list of {kind, id, ...}. updates: {id: fields to store}.
    """
    events, updates = [], {}
    for sid, item in seen.items():
        old = known.get(sid)
        fields = {k: item[k] for k in ("name", "url", "image", "category", "price", "list_price", "available",
                                        "limited", "level")}
        fields.update(listed=True, misses=0)
        if old is None:
            events.append(_ev("new", item))
        elif not old["listed"]:
            events.append(_ev("back", item, last_seen=old["last_seen"]))
        else:
            if old["available"] and not item["available"]:
                events.append(_ev("sold_out", item))
            elif not old["available"] and item["available"]:
                events.append(_ev("restock", item))
            elif item["limited"] and item["available"] and _lower(item["level"], old["level"]):
                events.append(_ev("low", item, was=old["level"]))
            if old["price"] is not None and item["price"] is not None and item["price"] != old["price"]:
                events.append(_ev("price", item, was=old["price"]))
        updates[sid] = fields

    for sid, old in known.items():
        if sid in seen or not old["listed"]:
            continue
        misses = old["misses"] + 1
        if misses >= MISSES_BEFORE_GONE:
            events.append(_ev("gone", old, id=sid))
            updates[sid] = {"listed": False, "misses": misses}
        else:
            updates[sid] = {"misses": misses}
    return events, updates


def _ev(kind, item, **extra):
    e = {"kind": kind, "id": item.get("id"), "name": item["name"], "url": item["url"], "image": item["image"],
         "price": item["price"], "limited": item["limited"], "level": item["level"]}
    e.update(extra)
    return e


def _lower(new, old):
    if new not in LEVELS or old not in LEVELS:
        return False
    return LEVELS.index(new) > LEVELS.index(old)
