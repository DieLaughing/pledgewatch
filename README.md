# Pledge Watch

Every Star Citizen ship in the RSI pledge store, and every way to buy it, on one page. Plus a Discord and Fluxer bot
that posts when ships come in, sell out, change price or leave.

**Live:** https://pledgewatch.inpints.com · no accounts, no cookies, no tracking.

## What it shows

- **Each ship's editions side by side:** standard, warbond, 10 Year and others, with their prices and the insurance
  each one includes (6 months, 10 years, lifetime).
- **In game vs pledge:** where you can buy or rent the ship for aUEC, how many hours of play that is at your own rate,
  and how much aUEC each pledge dollar is worth.
- **Insurance claim and expedite times** (and the expedite cost in aUEC), from the game files.
- **Price history:** past standard and warbond prices with dates, including the lowest and the last warbond.
- **Upgrade costs:** pick a ship you own and see what upgrading to each other ship costs.
- **Cargo grids** drawn from above, with every box labelled in SCU.
- **Loaners** for ships that aren't flyable yet, and flight-status changes as they happen.
- **A change log** of everything that came in, sold out, changed price or left.

It reads the **public** store, the one you see when logged out, so Concierge and subscriber early access isn't
included.

## The bot

Add it to your Discord server from the website, then an admin runs `/alerts setup` and picks a channel (and
optionally a role to ping). It's limited to 75 servers; if it's full, run your own copy (below).

| Command | What it does |
|---|---|
| `/watch <ship>` | Ping me when a matching ship comes in, restocks, runs low or changes price |
| `/unwatch <ship>` / `/unwatch all` | Stop |
| `/watching` | The ships you're watching |
| `/store [ship]` | Is it in the store right now? |
| `/alerts setup` · `status` · `off` | Server admins: where alerts go |

On Fluxer the same commands are typed with `!` (`!watch Idris`), since Fluxer bots can't register slash commands yet.

## Run your own

You need Docker. The image builds the website and runs the store checker, the bots and the website in one small
container (about 60 MB of memory).

```sh
git clone https://github.com/DieLaughing/pledgewatch && cd pledgewatch
cp .env.example settings.env      # fill in your bot tokens, or leave them empty for the website only
mkdir -p data                     # owned by you, so the container (a normal user) can write to it
docker build -t pledgewatch .
docker run -d --name pledgewatch --restart unless-stopped \
  -p 127.0.0.1:8794:8794 -v "$PWD/data:/data" --env-file settings.env pledgewatch
```

The website is then on port 8794. Put it behind a reverse proxy or a tunnel for HTTPS. Data (a SQLite database and
cached ship pictures) lives in `./data`.

**Discord bot:** create an application at https://discord.com/developers/applications, copy the bot token and the
application ID into `settings.env`, and invite it with the "Add to Discord" link your site shows (it asks for View
Channels, Send Messages, Embed Links, Read Message History and Mention Everyone, the last so role pings work).

### Develop

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest              # tests
.venv/bin/python -m pw once             # one store check, prints what changed
cd web && npm install && npm run build  # the website (Preact + Vite)
```

`deploy.sh` is the maintainer's build-on-the-server script; it reads `HOST` and `COMPOSE_DIR` from a `deploy.env`.

## How it works

- `pw/store.py` reads the pledge store's listing (no login), `pw/diff.py` turns two looks into changes, and
  `pw/watcher.py` runs that every 5 minutes and logs them in SQLite.
- `pw/post.py` posts changes to every server that set up alerts; `pw/bots.py` answers commands on Discord and Fluxer.
- `pw/catalog.py`, `pw/ingame.py` and `pw/cargo.py` refresh RSI's Ship Matrix and Loaner Ship Matrix, the Star Citizen
  Wiki, UEX and sc-cargo.space once a day.
- `pw/site.py` serves the page with its data inlined, so a visit is one request; ship pictures are fetched once and
  served locally, so visitors never contact RSI.

## Data and credits

Not affiliated with Cloud Imperium Games or Roberts Space Industries. Data comes from public sources: see
[THIRD_PARTY.md](THIRD_PARTY.md) for each one and its licence. Always check the RSI store before you buy.
[Privacy](https://pledgewatch.inpints.com/privacy) · [Terms](https://pledgewatch.inpints.com/terms)

## Licence

AGPL-3.0-or-later. If you run a modified copy for others, share your changes.
