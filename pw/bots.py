"""Listen for commands on Discord (real slash commands) and Fluxer (text commands like !watch; Fluxer bots can't
register slash commands yet). Both call the same functions in commands.py."""
import asyncio
import logging
import random

import aiohttp
import discord
from discord import app_commands

from . import commands as cmd

log = logging.getLogger("pledgewatch")


# Discord

def discord_client(db, guild_id):
    client = discord.Client(intents=discord.Intents(guilds=True))
    tree = app_commands.CommandTree(client)
    p = "discord"

    @tree.command(name="watch", description="Get pinged when a ship comes into the public store")
    @app_commands.describe(ship="Ship name, or part of it, like Idris")
    async def watch(inter: discord.Interaction, ship: str):
        await inter.response.send_message(cmd.watch(db, p, str(inter.user.id), ship), ephemeral=True)

    @watch.autocomplete("ship")
    async def watch_names(inter: discord.Interaction, current: str):
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in cmd.names(db, current)]

    @tree.command(name="unwatch", description="Stop getting pinged about a ship")
    @app_commands.describe(ship="A ship you're watching, or all")
    async def unwatch(inter: discord.Interaction, ship: str):
        await inter.response.send_message(cmd.unwatch(db, p, str(inter.user.id), ship), ephemeral=True)

    @unwatch.autocomplete("ship")
    async def unwatch_names(inter: discord.Interaction, current: str):
        mine = cmd._mine(db, p, str(inter.user.id)) + ["all"]
        return [app_commands.Choice(name=q, value=q) for q in mine if cmd.norm(current) in q][:25]

    @tree.command(name="watching", description="The ships you're watching")
    async def watching(inter: discord.Interaction):
        await inter.response.send_message(cmd.watching(db, p, str(inter.user.id)), ephemeral=True)

    @tree.command(name="store", description="Is a ship in the public store right now?")
    @app_commands.describe(ship="Ship name, or leave empty for a summary")
    async def store(inter: discord.Interaction, ship: str | None = None):
        await inter.response.send_message(cmd.store(db, ship), ephemeral=True)

    store.autocomplete("ship")(watch_names)

    @tree.command(name="pledgewatch", description="What Pledge Watch does and how to use it")
    async def help_(inter: discord.Interaction):
        await inter.response.send_message(cmd.HELP.format(p="/"), ephemeral=True)

    async def setup_hook():
        guild = discord.Object(id=int(guild_id))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)  # server-only commands show up instantly
        log.info("discord: slash commands ready")

    client.setup_hook = setup_hook
    return client


# Fluxer

FLUXER_COMMANDS = {"watch", "unwatch", "watching", "store", "pledgewatch", "help"}


def fluxer_reply(db, content, user):
    """Reply text for a Fluxer message, or None if it isn't for us. Accepts !watch and /watch."""
    if not content or content[0] not in "!/":
        return None
    name, _, arg = content[1:].strip().partition(" ")
    name, arg = name.lower(), arg.strip()
    if name not in FLUXER_COMMANDS:
        return None
    p = "fluxer"
    if name == "watch":
        return cmd.watch(db, p, user, arg) if arg else "Which ship? Like `!watch Idris`."
    if name == "unwatch":
        return cmd.unwatch(db, p, user, arg) if arg else "Which ship? Like `!unwatch Idris`, or `!unwatch all`."
    if name == "watching":
        return cmd.watching(db, p, user)
    if name == "store":
        return cmd.store(db, arg)
    return cmd.HELP.format(p="!")


async def fluxer_loop(db, api, token, channel_id):
    """Stay connected to the Fluxer gateway and answer commands in our channel and in DMs. Reconnects forever."""
    auth = {"Authorization": f"Bot {token}"}
    delay = 5
    while True:
        try:
            async with aiohttp.ClientSession(headers=auth) as s:
                async with s.get(f"{api}/api/v1/gateway/bot") as r:
                    url = (await r.json())["url"]
                async with s.ws_connect(f"{url}?v=1&encoding=json", heartbeat=None, max_msg_size=0) as ws:
                    await _fluxer_session(db, s, ws, api, token, channel_id)
                    delay = 5
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("fluxer: connection lost (%s), retrying in %ds", e, delay)
        await asyncio.sleep(delay + random.random())
        delay = min(delay * 2, 300)


async def _fluxer_session(db, s, ws, api, token, channel_id):
    hello = await ws.receive_json()
    interval = hello["d"]["heartbeat_interval"] / 1000
    seq = None
    me = None

    async def beat():
        await asyncio.sleep(interval * random.random())
        while True:
            await ws.send_json({"op": 1, "d": seq})
            await asyncio.sleep(interval)

    await ws.send_json({"op": 2, "d": {"token": token,
                                       "properties": {"os": "linux", "browser": "pledgewatch", "device": "pledgewatch"}}})
    heart = asyncio.create_task(beat())
    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            p = msg.json()
            seq = p.get("s") or seq
            if p["op"] == 1:
                await ws.send_json({"op": 1, "d": seq})
            elif p["op"] in (7, 9):  # reconnect / invalid session: start over
                break
            elif p["op"] == 0 and p["t"] == "READY":
                me = p["d"]["user"]["id"]
                log.info("fluxer: connected as %s", p["d"]["user"].get("username"))
            elif p["op"] == 0 and p["t"] == "MESSAGE_CREATE":
                d = p["d"]
                author = d.get("author") or {}
                if author.get("bot") or author.get("id") == me:
                    continue
                if d.get("guild_id") and d.get("channel_id") != channel_id:
                    continue  # in the server, only answer in the Ship Hunter channel; DMs are fine
                text = fluxer_reply(db, d.get("content", ""), author.get("id"))
                if text:
                    body = {"content": text, "message_reference": {"message_id": d["id"]},
                            "allowed_mentions": {"parse": [], "replied_user": False}}
                    async with s.post(f"{api}/api/v1/channels/{d['channel_id']}/messages", json=body) as r:
                        if r.status >= 300:
                            log.warning("fluxer: reply failed %s %s", r.status, (await r.text())[:200])
    finally:
        heart.cancel()
