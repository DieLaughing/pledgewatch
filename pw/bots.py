"""Listen for commands on Discord (real slash commands) and Fluxer (text commands like !watch; Fluxer bots can't
register slash commands yet). Both call the same functions in commands.py."""
import asyncio
import difflib
import logging
import random

import aiohttp
import discord
from discord import app_commands

from . import commands as cmd
from . import servers

log = logging.getLogger("pledgewatch")


# Discord

def discord_client(db, home_guild, poster=None):
    """Slash commands for every server the bot is in. `poster` is the App used to send /alerts setup's test post."""
    client = discord.Client(intents=discord.Intents(guilds=True))
    tree = app_commands.CommandTree(client)
    p = "discord"

    def where(inter):
        return str(inter.guild_id) if inter.guild_id else home_guild

    def no_channel_note(inter):
        if inter.guild_id and not (servers.get(db, p, str(inter.guild_id)) or {"active": 0})["active"]:
            return ("\n-# This server has no alert channel yet, so I can't ping you here. "
                    "Ask a server admin to run `/alerts setup`.")
        return ""

    @tree.command(name="watch", description="Get pinged about a ship, or anything over a price (for upgrades/CCUs)")
    @app_commands.describe(ship="Ship name, or part of it, like Idris",
                           above="Any ship or upgrade worth more than this many dollars, like 520",
                           from_="A ship you own: upgrades it can take, with what they cost from it")
    @app_commands.rename(from_="from")
    @app_commands.guild_only()
    async def watch(inter: discord.Interaction, ship: str | None = None,
                    above: app_commands.Range[int, 1, 99999] | None = None, from_: str | None = None):
        given = [q for q in (ship, above and f"above:{above}", from_ and f"from:{from_}") if q]
        if len(given) != 1:
            reply = "Pick one: a `ship`, `above` a price, or `from` a ship you own."
        else:
            reply = cmd.watch(db, p, str(inter.user.id), given[0], guild=where(inter)) + no_channel_note(inter)
        await inter.response.send_message(reply, ephemeral=True)

    @watch.autocomplete("ship")
    async def watch_names(inter: discord.Interaction, current: str):
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in cmd.names(db, current)]

    @watch.autocomplete("from_")
    async def from_names(inter: discord.Interaction, current: str):
        rows = db.execute("SELECT name FROM upgrade_ships ORDER BY name").fetchall()
        return [app_commands.Choice(name=r[0][:100], value=r[0][:100]) for r in rows
                if cmd.norm(current) in cmd.norm(r[0])][:25]

    @tree.command(name="unwatch", description="Stop getting pinged about a ship")
    @app_commands.describe(ship="Something you're watching, or all")
    @app_commands.guild_only()
    async def unwatch(inter: discord.Interaction, ship: str):
        await inter.response.send_message(cmd.unwatch(db, p, str(inter.user.id), ship), ephemeral=True)

    @unwatch.autocomplete("ship")
    async def unwatch_names(inter: discord.Interaction, current: str):
        mine = cmd._mine(db, p, str(inter.user.id)) + ["all"]
        return [app_commands.Choice(name=q[:100], value=q[:100]) for q in mine if cmd.norm(current) in cmd.norm(q)][:25]

    @tree.command(name="watching", description="What you're watching")
    async def watching(inter: discord.Interaction):
        await inter.response.send_message(cmd.watching(db, p, str(inter.user.id)), ephemeral=True)

    @tree.command(name="store", description="Is a ship in the public store right now?")
    @app_commands.describe(ship="Ship name, or leave empty for a summary")
    async def store(inter: discord.Interaction, ship: str | None = None):
        await inter.response.send_message(cmd.store(db, ship), ephemeral=True)

    store.autocomplete("ship")(watch_names)

    @tree.command(name="pledgewatch", description="What Pledge Watch does and how to use it")
    async def help_(inter: discord.Interaction):
        await inter.response.send_message(cmd.HELP.format(p="/") + cmd.ADMIN_HELP, ephemeral=True)

    alerts = app_commands.Group(name="alerts", description="Where this server gets Pledge Watch store alerts",
                                guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    @alerts.command(name="setup", description="Post store alerts in a channel, optionally pinging a role")
    @app_commands.describe(channel="Channel for alerts", role="Role to ping when a ship comes in (optional)")
    async def alerts_setup(inter: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None):
        perms = channel.permissions_for(inter.guild.me)
        missing = [n for n, ok in (("View Channel", perms.view_channel), ("Send Messages", perms.send_messages),
                                   ("Embed Links", perms.embed_links)) if not ok]
        if missing:
            await inter.response.send_message(f"I can't post in {channel.mention} yet: I'm missing **{', '.join(missing)}** "
                                              "there. Give me those in the channel's permissions, then run this again.",
                                              ephemeral=True)
            return
        await inter.response.defer(ephemeral=True, thinking=True)
        text = (f"Pledge Watch will post RSI pledge store alerts here"
                + (f" and ping {role.mention} when a ship comes in" if role else "") + ". Try `/watch Idris`.")
        try:
            await asyncio.to_thread(poster.send, str(channel.id), {"content": text, "allowed_mentions": {"parse": []}})
        except Exception as e:
            await inter.followup.send(f"I couldn't post a test message in {channel.mention} ({e}). Check my permissions "
                                      "there and run this again.", ephemeral=True)
            return
        servers.save(db, p, str(inter.guild_id), str(channel.id), str(role.id) if role else "")
        note = ""
        if role and not role.mentionable and not perms.mention_everyone:
            note = (f"\n-# {role.mention} isn't mentionable and I don't have Mention Everyone, so the ping won't "
                    "notify anyone. Make the role mentionable or give me that permission.")
        await inter.followup.send(f"Done. Alerts go to {channel.mention}" + (f", pinging {role.mention}" if role else "")
                                  + ". I posted a test message there." + note, ephemeral=True)

    @alerts.command(name="status", description="Show where this server's alerts go")
    async def alerts_status(inter: discord.Interaction):
        row = servers.get(db, p, str(inter.guild_id))
        if not row:
            text = "Alerts aren't set up here. Run `/alerts setup` and pick a channel."
        elif not row["active"]:
            text = (f"Alerts are **off** for this server" + (f" ({row['note'][:120]})" if row["note"] else "")
                    + ". Run `/alerts setup` to turn them back on.")
        else:
            text = f"Alerts go to <#{row['channel_id']}>" + (f", pinging <@&{row['role_id']}>" if row["role_id"] else "") + "."
        await inter.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @alerts.command(name="off", description="Stop posting store alerts in this server")
    async def alerts_off(inter: discord.Interaction):
        servers.switch_off(db, p, str(inter.guild_id), "turned off with /alerts off")
        await inter.response.send_message("Alerts are off for this server. `/alerts setup` turns them back on.", ephemeral=True)

    tree.add_command(alerts)

    @client.event
    async def on_ready():
        servers.set_count(db, len(client.guilds))

    @client.event
    async def on_guild_join(guild):
        if servers.over_cap(len(client.guilds), str(guild.id), home_guild):
            # Say why before leaving: the system channel, else the first channel it may post in.
            chans = ([guild.system_channel] if guild.system_channel else []) + list(guild.text_channels)
            for ch in chans:
                if ch.permissions_for(guild.me).send_messages:
                    try:
                        await ch.send(servers.FULL_NOTE.format(cap=servers.MAX_SERVERS))
                    except discord.HTTPException:
                        continue
                    break
            await guild.leave()
            log.info("discord: at the %d-server cap, left a new server", servers.MAX_SERVERS)
            return
        servers.set_count(db, len(client.guilds))
        log.info("discord: added to a server (%d now)", len(client.guilds))

    @client.event
    async def on_guild_remove(guild):
        servers.forget(db, p, str(guild.id))
        servers.set_count(db, len(client.guilds))
        log.info("discord: removed from a server; its settings and watches are deleted (%d now)", len(client.guilds))

    async def setup_hook():
        # Commands are global so every server gets them. Older versions registered them on the home server only;
        # clear those so they don't show up twice there.
        if home_guild:
            home = discord.Object(id=int(home_guild))
            tree.clear_commands(guild=home)
            await tree.sync(guild=home)
        await tree.sync()
        log.info("discord: slash commands ready (global)")

    client.setup_hook = setup_hook
    return client


# Fluxer

FLUXER_COMMANDS = {"watch", "unwatch", "watching", "store", "pledgewatch", "help"}


def fluxer_reply(db, content, user, guild=""):
    """Reply text for a Fluxer message, or None if it isn't for us. Accepts !watch and /watch."""
    if not content or content[0] not in "!/":
        return None
    name, _, arg = content[1:].strip().partition(" ")
    name, arg = name.lower(), arg.strip()
    if name not in FLUXER_COMMANDS:
        close = difflib.get_close_matches(name, ["watch", "unwatch", "watching", "store"], n=1, cutoff=0.75)
        return f"Did you mean `!{close[0]}`? `!help` lists everything." if close and content[0] == "!" else None
    p = "fluxer"
    if name == "watch":
        return cmd.watch(db, p, user, arg, guild=guild) if arg else "Which ship? Like `!watch Idris`, `!watch above:520` or `!watch from:M2 Hercules`."
    if name == "unwatch":
        return cmd.unwatch(db, p, user, arg) if arg else "Which ship? Like `!unwatch Idris`, or `!unwatch all`."
    if name == "watching":
        return cmd.watching(db, p, user)
    if name == "store":
        return cmd.store(db, arg)
    return cmd.HELP.format(p="!")


async def fluxer_loop(db, api, token, channel_id, home_guild=""):
    """Stay connected to the Fluxer gateway and answer commands in our channel and in DMs. Reconnects forever."""
    auth = {"Authorization": f"Bot {token}"}
    delay = 5
    while True:
        try:
            async with aiohttp.ClientSession(headers=auth) as s:
                async with s.get(f"{api}/api/v1/gateway/bot") as r:
                    url = (await r.json())["url"]
                async with s.ws_connect(f"{url}?v=1&encoding=json", heartbeat=None, max_msg_size=0) as ws:
                    await _fluxer_session(db, s, ws, api, token, channel_id, home_guild)
                    delay = 5
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("fluxer: connection lost (%s), retrying in %ds", e, delay)
        await asyncio.sleep(delay + random.random())
        delay = min(delay * 2, 300)


async def _fluxer_session(db, s, ws, api, token, channel_id, home_guild):
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
                text = fluxer_reply(db, d.get("content", ""), author.get("id"), d.get("guild_id") or home_guild)
                if text:
                    body = {"content": text, "message_reference": {"message_id": d["id"]},
                            "allowed_mentions": {"parse": [], "replied_user": False}}
                    async with s.post(f"{api}/api/v1/channels/{d['channel_id']}/messages", json=body) as r:
                        if r.status >= 300:
                            log.warning("fluxer: reply failed %s %s", r.status, (await r.text())[:200])
    finally:
        heart.cancel()
