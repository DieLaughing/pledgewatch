"""python -m pw          run the store checker, post changes, and answer commands on Discord and Fluxer
python -m pw once     run one check and print what changed (posts nothing)
python -m pw hello    post a test message to each configured channel"""
import asyncio
import logging
import os
import sys

from . import db as store_db
from .post import apps_from_env
from .watcher import check, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.ERROR)  # "PyNaCl is not installed": no voice, on purpose
cmd = sys.argv[1:]
path = os.path.join(os.environ.get("PW_DATA", "data"), "pledgewatch.db")
if cmd != ["hello"]:
    os.makedirs(os.path.dirname(path), exist_ok=True)


async def main():
    env = os.environ
    db = store_db.connect(path)  # for command replies, on this event loop's thread
    tasks = [run(path, apps_from_env())]
    if env.get("DISCORD_TOKEN") and env.get("DISCORD_GUILD_ID"):
        from .bots import discord_client
        tasks.append(discord_client(db, env["DISCORD_GUILD_ID"]).start(env["DISCORD_TOKEN"]))
    if env.get("FLUXER_TOKEN") and env.get("FLUXER_CHANNEL_ID"):
        from .bots import fluxer_loop
        tasks.append(fluxer_loop(db, env["FLUXER_API"].rstrip("/"), env["FLUXER_TOKEN"], env["FLUXER_CHANNEL_ID"]))
    await asyncio.gather(*tasks)


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
    asyncio.run(main())
else:
    sys.exit(__doc__)
