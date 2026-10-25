from pw import commands as cmd
from pw import db as store_db
from pw.bots import fluxer_reply
from pw.post import message
from pw.watcher import check

DAY = 86400


def ship(sid, name, price, limited=False, level="high"):
    return {"id": sid, "name": name, "url": f"https://x/{sid}", "image": "", "category": "Standalone Ships",
            "price": price, "list_price": price, "available": True, "limited": limited, "level": level, "qty": 0}


def setup(tmp_path):
    db = store_db.connect(str(tmp_path / "t.db"))
    check(db, [ship("1", "Carrack", 60000), ship("2", "Idris-P", 150000, True), ship("3", "Idris-M", 125000, True)],
          now=DAY)
    return db


def test_watch_unwatch_watching(tmp_path):
    db = setup(tmp_path)
    assert "in the store: Carrack ($600)" in cmd.watch(db, "discord", "u1", "carrack")
    assert "already watching" in cmd.watch(db, "discord", "u1", "CARRACK!")
    reply = cmd.watch(db, "discord", "u1", "Kraken")
    assert "not in the public store" in reply and "check the spelling" in reply
    assert "carrack" in cmd.watching(db, "discord", "u1") and "kraken" in cmd.watching(db, "discord", "u1")
    assert cmd.watching(db, "fluxer", "u1").startswith("You're not watching")  # apps are separate
    assert cmd.unwatch(db, "discord", "u1", "kraken") == "Stopped watching **kraken**."
    assert "all 1" in cmd.unwatch(db, "discord", "u1", "all")


def test_watch_rejects_junk_and_caps(tmp_path):
    db = setup(tmp_path)
    assert "two letters" in cmd.watch(db, "discord", "u1", "!")
    for i in range(cmd.MAX_WATCHES):
        cmd.watch(db, "discord", "u1", f"ship {i}")
    assert "the limit" in cmd.watch(db, "discord", "u1", "carrack")


def test_store_answers(tmp_path):
    db = setup(tmp_path)
    assert cmd.store(db).startswith("3 ships are in the public store right now, 2 of them limited")
    r = cmd.store(db, "idris")
    assert "Idris-P**: $1,500, limited, high" in r and "Idris-M" in r and "public store" in r
    assert "don't know a ship called **polaris**" in cmd.store(db, "Polaris", now=DAY * 3)


def test_watchers_pinged_on_matching_events_only(tmp_path):
    db = setup(tmp_path)
    cmd.watch(db, "discord", "u1", "idris")
    cmd.watch(db, "discord", "u2", "idris-p")
    cmd.watch(db, "fluxer", "f1", "idris")
    idris_m = {"kind": "new", "name": "Idris-M"}
    assert cmd.watchers(db, "discord", idris_m) == ["u1"]
    assert cmd.watchers(db, "discord", {"kind": "new", "name": "Idris-P"}) == ["u1", "u2"]
    assert cmd.watchers(db, "fluxer", idris_m) == ["f1"]
    assert cmd.watchers(db, "discord", {"kind": "gone", "name": "Idris-M"}) == []


def test_message_mentions_role_and_watchers():
    e = {"kind": "price", "name": "Carrack", "url": "u", "image": "", "price": 54000, "was": 60000,
         "limited": False, "level": "high"}
    m = message(e, 1, role="42", users=["u1"])
    assert m["content"] == "<@u1>" and m["allowed_mentions"] == {"roles": [], "users": ["u1"]}
    assert "Public store" in m["embeds"][0]["footer"]["text"]


def test_fluxer_text_commands(tmp_path):
    db = setup(tmp_path)
    assert fluxer_reply(db, "hello there", "f1") is None
    assert fluxer_reply(db, "!shrug", "f1") is None
    assert "Which ship" in fluxer_reply(db, "!watch", "f1")
    assert "Watching **idris**" in fluxer_reply(db, "!watch Idris", "f1")
    assert "Watching **carrack**" in fluxer_reply(db, "/watch carrack", "f1")
    assert "idris" in fluxer_reply(db, "!WATCHING", "f1")
    assert "!watch <ship>" in fluxer_reply(db, "!help", "f1")
