import logging
import os
import sys

from . import db as store_db
from .watcher import check, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
path = os.path.join(os.environ.get("PW_DATA", "data"), "pledgewatch.db")
os.makedirs(os.path.dirname(path), exist_ok=True)

if sys.argv[1:] == ["once"]:
    db = store_db.connect(path)
    events = check(db)
    listed = sum(1 for s in store_db.known(db).values() if s["listed"])
    print(f"{listed} ships listed, {len(events)} change(s): {[e['kind'] + ' ' + e.get('name', '') for e in events]}")
else:
    run(path)
