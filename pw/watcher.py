"""The store checker: every few minutes, read the store, work out what changed, and log it."""
import logging
import os
import time

from . import db as store_db
from .diff import diff
from .store import StoreError, fetch

log = logging.getLogger("pledgewatch")

INTERVAL = int(os.environ.get("PW_INTERVAL", "300"))
# After this many failed checks in a row, log a "can't read the store" event (once), and a "back" event on recovery.
FAILS_BEFORE_ALERT = 3
# If a check returns far fewer ships than we have listed, treat it as a bad read instead of a mass "left the store".
MIN_SHARE = 0.5


def check(db, items=None, now=None):
    """Run one check. Returns the events it logged. `items` is for tests; normally the store is fetched."""
    try:
        items = fetch() if items is None else items
    except StoreError as e:
        return _failed(db, str(e), now)
    known = store_db.known(db)
    listed = sum(1 for s in known.values() if s["listed"])
    if listed and len(items) < listed * MIN_SHARE:
        return _failed(db, f"store returned {len(items)} ships, expected about {listed}", now)

    first_run = not known
    events, updates = diff(known, {i["id"]: i for i in items})
    if first_run:
        events = []  # the first look is the baseline, not 70 "new ship" alerts
    fails = store_db.get_state(db, "fails", 0)
    if fails >= FAILS_BEFORE_ALERT:
        events.append({"kind": "store_ok", "id": None, "fails": fails})
    store_db.save(db, updates, events, now)
    store_db.set_state(db, "fails", 0)
    store_db.set_state(db, "last_ok", int(now or time.time()))
    return events


def _failed(db, reason, now):
    fails = store_db.get_state(db, "fails", 0) + 1
    store_db.set_state(db, "fails", fails)
    log.warning("check failed (%d in a row): %s", fails, reason)
    if fails == FAILS_BEFORE_ALERT:
        store_db.add_event(db, "store_down", {"reason": reason, "fails": fails,
                                              "since": store_db.get_state(db, "last_ok")}, now)
        return [{"kind": "store_down", "reason": reason}]
    return []


def run(path):
    db = store_db.connect(path)
    log.info("watching the RSI store every %ds, database %s", INTERVAL, path)
    while True:
        started = time.monotonic()
        for e in check(db):
            log.info("%s: %s", e["kind"], e.get("name", e.get("reason", "")))
        time.sleep(max(30, INTERVAL - (time.monotonic() - started)))
