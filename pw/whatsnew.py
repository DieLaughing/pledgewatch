"""The site's "What's new" page: changes visitors and bot users can see, newest first. Backend-only work isn't listed.
Add an entry here with each user-facing release; the header shows a dot until a visitor has seen the newest one."""
import html

ENTRIES = [
    ("2026-10-27", [
        "New sort: Value, most aUEC per $ (in-game price divided by pledge price). While it's on, each card's In game "
        "box shows that figure instead of hours of play.",
        "Ships RSI only sells during sales or in limited runs get a Sale only or Limited runs tag (ships on their way "
        "out get Retiring), and Filters has a new How it's sold group (Always in store, Sale only). This comes from the "
        "Star Citizen Wiki, not RSI, so treat it as a good guess.",
        "The Limited filter is now called Limited stock, to tell it apart from sale-only ships.",
    ]),
    ("2026-10-26", [
        "Upgrades (CCUs): every ship card lists the upgrades to it on sale now, standard and warbond, with what the "
        "warbond ones save.",
        "Pick a ship you own under Filters → Upgrades and each card shows exactly what it can upgrade into and what it "
        "costs from your ship, straight from RSI's upgrade tool. Some warbond upgrades only apply from certain ships, "
        "and this tells you which.",
        "New filters: Upgrade deals and Upgradable. They include ships you can currently only get by upgrading.",
        "Filters now live in one panel, grouped, so the list starts higher up the page, especially on phones.",
        "Bot: `/watch above:520` pings you when any ship or upgrade worth more than $520 comes in or gets cheaper, and "
        "`/watch from:<ship>` pings you about upgrades a ship you own can take, with the cost from it. "
        "On Fluxer: `!watch above:520`, `!watch from:M2`.",
        "Clearer upgrades: each card shows the ship's upgrade value with a ? that explains it, a \"What would I pay?\" "
        "shortcut, and a link to your RSI hangar, where upgrades are actually bought.",
        "This What's new page.",
        "Upgrade planner (Upgrade planner, top right): pick the ship you own and the one you want, and it finds the "
        "cheapest chain of upgrades on sale right now, with what each step costs and which ones need new money. Add "
        "upgrades you already have and routes can use them as free steps. Each card's upgrade line links to it.",
    ]),
    ("2026-10-25", [
        "Pledge Watch launched: every ship in the public RSI store, every edition side by side (standard, warbond, "
        "10 Year) with price and insurance.",
        "In game vs pledge: in-game buy and rent prices, hours of play at your own aUEC rate, insurance claim and "
        "expedite times, and price history.",
        "Weapons per ship, gold standard status, cargo grids, loaners for ships that aren't flyable yet, and sorting by "
        "newest release.",
        "Discord and Fluxer bot: store alerts in your channel and `/watch <ship>` pings. Any Discord server can add it.",
    ]),
]

# The date plus how many items it has, so adding to today's entry shows the dot again: "2026-10-26" < "2026-10-26#8".
NEWEST = f"{ENTRIES[0][0]}#{len(ENTRIES[0][1])}"


def _date(d):
    import datetime
    t = datetime.date.fromisoformat(d)
    return f"{t:%B} {t.day}, {t.year}"


def _item(text):
    parts = html.escape(text).split("`")
    return "".join(f"<code>{p}</code>" if i % 2 else p for i, p in enumerate(parts))


def page():
    sections = "".join(
        f'<h2><time datetime="{d}">{_date(d)}</time></h2><ul>' + "".join(f"<li>{_item(t)}</li>" for t in items) + "</ul>"
        for d, items in ENTRIES)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>What's new · Pledge Watch</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><meta name="color-scheme" content="light dark">
<style>body{{max-width:42rem;margin:0 auto;padding:32px 16px;font:16px/1.6 system-ui,sans-serif}}
h1{{font-size:26px}}h2{{font-size:17px;margin-top:28px}}li{{margin:6px 0}}a{{color:#b26b00}}code{{font-size:14px}}</style></head><body>
<p><a href="/">← Pledge Watch</a></p>
<h1>What's new</h1>
<p>Changes you can see on the site or in the bot, newest first.</p>
{sections}
</body></html>"""
