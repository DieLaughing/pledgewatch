from pw.release import key, patch_of


def test_patch_values():
    assert patch_of("| addedinversion = Alpha 4.8.0\n") == "4.8.0"
    assert patch_of("| addedinversion = Patch V0.9.2.1\n") == "0.9.2.1"
    assert patch_of("| addedinversion = Alpha 3.20.0b\n") == "3.20.0"
    assert patch_of("| addedinversion = Hangar Module\n") == "0"
    assert patch_of("| addedinversion = Alpha 4.x.x\n") == ""  # concept placeholder
    assert patch_of("| addedinversion = \n") == "" and patch_of("no box") == ""


def test_order():
    assert sorted(["3.8.0", "3.24.3", "0", "4.10.2", "0.9.2.1"], key=key) == ["0", "0.9.2.1", "3.8.0", "3.24.3", "4.10.2"]
