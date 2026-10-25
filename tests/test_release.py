from pw.db import connect
from pw.release import gold, gold_rows, key, patch_of


def test_patch_values():
    assert patch_of("| addedinversion = Alpha 4.8.0\n") == "4.8.0"
    assert patch_of("| addedinversion = Patch V0.9.2.1\n") == "0.9.2.1"
    assert patch_of("| addedinversion = Alpha 3.20.0b\n") == "3.20.0"
    assert patch_of("| addedinversion = Hangar Module\n") == "0"
    assert patch_of("| addedinversion = Alpha 4.x.x\n") == ""  # concept placeholder
    assert patch_of("| addedinversion = \n") == "" and patch_of("no box") == ""


def test_order():
    assert sorted(["3.8.0", "3.24.3", "0", "4.10.2", "0.9.2.1"], key=key) == ["0", "0.9.2.1", "3.8.0", "3.24.3", "4.10.2"]


PIPELINE = """==== Gold standard ====
{| class="wikitable sortable"
|+ List of gold standard vehicles
! Name !! Manufacturer !! Status !! Patch
|-
| [[Sabre]] || [[Aegis Dynamics]] || Implemented ||{{Alpha|3.14.0}}
|-
| [[Retaliator]] || [[Aegis Dynamics]] || In production || N/A
|-
| [[A2 Hercules Starlifter]] || [[Crusader Industries]] || Implemented || {{Alpha|3.15.0}}
|-
| [[Sabre Raven]] || [[Aegis Dynamics]] || Implemented || {{Alpha|3.23.1}}
|-
| [[:Category:Aurora Mk I|Aurora Mk I]]|| [[Roberts Space Industries]] || Implemented || {{Alpha|4.6.0}}
|-
|}
"""


def test_gold_table():
    assert gold_rows(PIPELINE) == [("Sabre", "done", "3.14.0"), ("Retaliator", "in progress", ""),
                                   ("A2 Hercules Starlifter", "done", "3.15.0"), ("Sabre Raven", "done", "3.23.1"),
                                   ("Aurora Mk I", "done", "4.6.0")]
    assert gold_rows("no table here") == []


def test_gold_matches_the_most_specific_row(tmp_path):
    db = connect(str(tmp_path / "t.db"))
    db.executemany("INSERT INTO gold VALUES (?,?,?)", gold_rows(PIPELINE))
    for name in ("Sabre", "Sabre Comet", "Sabre Raven EX", "A2 Hercules", "Aurora Mk I LN", "Aurora Mk II", "Gladius"):
        db.execute("INSERT INTO catalog (name, key) VALUES (?, ?)", (name, name.lower()))
    g = gold(db)
    assert g["Sabre"] == {"status": "done", "patch": "3.14.0", "family": ""}
    assert g["Sabre Comet"]["family"] == "Sabre"
    assert g["Sabre Raven EX"] == {"status": "done", "patch": "3.23.1", "family": "Sabre Raven"}
    assert g["A2 Hercules"]["family"] == "" and g["Aurora Mk I LN"]["family"] == "Aurora Mk I"
    assert "Aurora Mk II" not in g and "Gladius" not in g
