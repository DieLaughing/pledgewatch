"""Where alerts go: one row per Discord server (and the Fluxer community) with its alert channel and ping role.

Servers set themselves up with /alerts setup. The owner's own Discord server and Fluxer community come from the
env file and are added on start, so they never need the command.
"""
import time


def seed(db, env):
    """Add the home server(s) from env if they aren't there yet. Never overwrites what /alerts setup saved."""
    for platform, prefix in (("discord", "DISCORD"), ("fluxer", "FLUXER")):
        guild, channel = env.get(f"{prefix}_GUILD_ID"), env.get(f"{prefix}_CHANNEL_ID")
        if env.get(f"{prefix}_TOKEN") and guild and channel:
            with db:
                db.execute("INSERT OR IGNORE INTO servers (platform, guild_id, channel_id, role_id, added) "
                           "VALUES (?,?,?,?,?)", (platform, guild, channel, env.get(f"{prefix}_ROLE_ID") or "", 0))
                # Watches made before servers existed belong to the home server.
                db.execute("UPDATE watches SET guild_id=? WHERE platform=? AND guild_id=''", (guild, platform))


def home(env, platform):
    return env.get(f"{platform.upper()}_GUILD_ID") or ""


def active(db):
    return db.execute("SELECT * FROM servers WHERE active=1 ORDER BY added").fetchall()


def get(db, platform, guild):
    return db.execute("SELECT * FROM servers WHERE platform=? AND guild_id=?", (platform, guild)).fetchone()


def save(db, platform, guild, channel, role):
    with db:
        db.execute("""INSERT INTO servers (platform, guild_id, channel_id, role_id, active, note, added) VALUES (?,?,?,?,1,'',?)
                      ON CONFLICT(platform, guild_id) DO UPDATE SET channel_id=excluded.channel_id,
                      role_id=excluded.role_id, active=1, note=''""", (platform, guild, channel, role or "", int(time.time())))


def switch_off(db, platform, guild, note):
    with db:
        db.execute("UPDATE servers SET active=0, note=? WHERE platform=? AND guild_id=?", (note, platform, guild))


def forget(db, platform, guild):
    """The bot left a server: drop its settings and its members' watches there."""
    with db:
        db.execute("DELETE FROM servers WHERE platform=? AND guild_id=?", (platform, guild))
        db.execute("DELETE FROM watches WHERE platform=? AND guild_id=?", (platform, guild))
