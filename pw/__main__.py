"""python -m pw          run the store checker and post changes
python -m pw once     run one check and print what changed (posts nothing)
python -m pw hello    post a test message to each configured channel"""
import logging
import os
import sys

from . import db as store_db
from .post import apps_from_env
from .watcher import check, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
cmd = sys.argv[1:]
path = os.path.join(os.environ.get("PW_DATA", "data"), "pledgewatch.db")
if cmd != ["hello"]:
    os.makedirs(os.path.dirname(path), exist_ok=True)

if cmd == ["once"]:
    db = store_db.connect(path)
    events = check(db)
    listed = sum(1 for s in store_db.known(db).values() if s["listed"])
    print(f"{listed} ships listed, {len(events)} change(s): {[e['kind'] + ' ' + e.get('name', '') for e in events]}")
elif cmd == ["hello"]:
    for app in apps_from_env():
        app.send({"content": "Pledge Watch is connected. Store alerts will show up in this channel.",
                  "allowed_mentions": {"parse": []}})
        print(f"posted to {app.name}")
elif not cmd:
    run(path, apps_from_env())
else:
    sys.exit(__doc__)
