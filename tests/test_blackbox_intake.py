"""Model-agnostic .dyr scanning, placement on the rig, DLL inspection and log parsing."""

import struct

import pytest

from blackbox.dll_inspect import inspect_dll
from blackbox.intake import load_targets, place_on_rig, scan_dyr
from blackbox.logparse import parse_log, suspect_states
from load_models import get_load_model

MIXED = """\
@! a comment line with a / slash
101 'GENROU' 1 6.5 0.05 0.5 0.05 4.0 0.0 1.8 1.75 0.3 0.6 0.2 0.15 0.1 0.3 /
101 'MAINBL10' '1' 1 0 0 0 0 0 0 0 0 0  1 0 0 0 0 0 0 0 0 0 /
101 'USRLODC' '1' 'PERCBL1U' 230 1 0 30 8 24 2 1 'PERC1 load' 0.8 0 0 0 8 0 0.05 0 0.1 1 1 1 1 0 0 1 0 0.7
 -0.7 0.9 0.5 0.05 0 0.6 0.05 1 0.5 0.02 0.05 0.02 /
7, 'CLODOW', '2', 35.00, 35.00, 5.00, 5.00, 10.00  /
202 'USRLOD' '1' 'MYLOAD' 12 1 3 4 2 3 202 305 0  0.9 0.1 2.0 1.0 /
305 'USRMDL' '1' 'MYGEN' 101 0 0 2 1 1 0.5 0.2 /
"""


def test_scan_types_every_record_without_knowing_the_models():
    recs = scan_dyr(MIXED)
    assert [r.record_type for r in recs] == ["GENROU", "MAINBL10", "USRLODC", "CLODOW", "USRLOD", "USRMDL"]
    assert [r.device for r in recs] == ["other", "load", "load", "load", "load", "machine"]
    std = recs[2]
    assert std.model == "PERCBL1U" and std.header["nc"] == 30 and std.scope == "bus" and std.load_id == "1"
    clod = recs[3]
    assert clod.scope == "owner" and clod.number == 7 and clod.load_id == "2"
    user = recs[4]
    assert user.icons == (202.0, 305.0, 0.0) and user.header["nc"] == 4


def test_an_unterminated_record_is_reported():
    recs = scan_dyr("101 'CLODBL' '1' 1 2 3 /\n102 'CLODBL' '1' 1 2")
    assert recs[0].error is None and recs[1].error == "no closing '/'"


def test_load_targets_group_the_records_of_one_load():
    targets = load_targets(scan_dyr(MIXED))
    labels = {t.label for t in targets}
    assert "MAINBL10 + PERCBL1U - bus 101, load '1'" in labels
    assert "CLODOW - owner 7, load '2'" in labels
    assert "MYLOAD - bus 202, load '1'" in labels


def test_placement_moves_only_the_bus_and_keeps_every_con():
    recs = scan_dyr(MIXED)
    target = next(t for t in load_targets(recs) if "PERCBL1U" in t.models)
    placed = place_on_rig(recs, target)
    joined = " ".join(placed.records)
    assert placed.records[0].startswith("{BUS} 'MAINBL10' '1'")
    assert "'PERC1 load'" in joined and "-0.7" in joined
    assert all(len(line) <= 80 for rec in placed.records for line in rec.splitlines())
    assert placed.rig == {"load_id": "1"}


def test_placement_of_a_subsystem_record_moves_the_rig_load_instead():
    recs = scan_dyr(MIXED)
    target = next(t for t in load_targets(recs) if t.models == ("CLODOW",))
    placed = place_on_rig(recs, target)
    assert placed.records[0].startswith("7 'CLODOW'")
    assert placed.rig == {"load_id": "2", "owner": 7}


def test_placement_maps_own_bus_icons_and_flags_other_buses():
    recs = scan_dyr(MIXED)
    target = next(t for t in load_targets(recs) if t.models == ("MYLOAD",))
    placed = place_on_rig(recs, target)
    assert "12 1 3 4 2 3 {BUS} 305 0" in placed.records[0]
    assert placed.expect_ncon == 4
    assert any("ICON(2) = 305" in f for f in placed.flags)


def test_the_apps_own_exports_scan_cleanly():
    for model_id in ("perc1_dll", "perc1_standard", "perc2_standard", "perc2_dll", "clod"):
        model = get_load_model(model_id)
        text = model.build_dyr_record(101, "1", dict(model.default_cons))
        targets = load_targets(scan_dyr(text))
        assert len(targets) == 1, model_id
        placed = place_on_rig(scan_dyr(text), targets[0])
        assert all(r.startswith("{BUS}") for r in placed.records)
    perc = scan_dyr(get_load_model("perc1_dll").build_dyr_record(101, "1", dict(get_load_model("perc1_dll").default_cons)))
    assert perc[0].header == {"ic": 12, "it": 1, "ni": 2, "nc": 173, "ns": 33, "nv": 250}


def test_a_perc2_record_scans_with_its_flags_and_57_cons():
    model = get_load_model("perc2_standard")
    recs = scan_dyr(model.build_dyr_record(101, "1", dict(model.default_cons)))
    perc2 = next(r for r in recs if r.model == "PERCBL2U")
    placed = place_on_rig(recs, load_targets(recs)[0])
    assert perc2.header["nc"] == 57 and perc2.header["ni"] == 6
    assert [r.split()[1] for r in placed.records] == ["'MAINBL10'", "'USRLODC'"]


def _tiny_dll(machine=0x8664, exports=("PERCBL",), imports=("libnotinstalled_rt.dll", "kernel32.dll")):
    """A minimal PE image: one section holding the export and import directories."""
    sec_rva, sec_raw = 0x1000, 0x200
    blob = bytearray(0x400)
    strings = {}
    pos = 0x100

    def put(s):
        nonlocal pos
        strings[s] = sec_rva + pos
        blob[pos:pos + len(s) + 1] = s.encode() + b"\0"
        pos += len(s) + 1

    for s in (*exports, *imports):
        put(s)
    names_rva = sec_rva + 0x300
    for i, s in enumerate(exports):
        struct.pack_into("<I", blob, 0x300 + 4 * i, strings[s])
    struct.pack_into("<III", blob, 0 + 20, len(exports), len(exports), 0)
    struct.pack_into("<I", blob, 0 + 32, names_rva)
    for i, s in enumerate(imports):
        struct.pack_into("<I", blob, 0x40 + 20 * i + 12, strings[s])
    pe = 0x80
    head = bytearray(sec_raw)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, pe)
    head[pe:pe + 4] = b"PE\0\0"
    opt_size = 240
    struct.pack_into("<HH", head, pe + 4, machine, 1)
    struct.pack_into("<H", head, pe + 20, opt_size)
    opt = pe + 24
    struct.pack_into("<H", head, opt, 0x20B)
    struct.pack_into("<II", head, opt + 112, sec_rva, 0x40)
    struct.pack_into("<II", head, opt + 120, sec_rva + 0x40, 0x40)
    sec = opt + opt_size
    struct.pack_into("<IIII", head, sec + 8, len(blob), sec_rva, len(blob), sec_raw)
    return bytes(head) + bytes(blob)


def test_dll_inspection(tmp_path):
    dll = tmp_path / "model.dll"
    dll.write_bytes(_tiny_dll())
    report = inspect_dll(str(dll), models=("PERCBL", "OTHER"))
    assert report.machine == "x64" and report.exports == ["PERCBL"]
    assert report.missing_imports == ["libnotinstalled_rt.dll"]
    assert not report.ok and any("libnotinstalled_rt.dll" in p for p in report.problems)
    assert any("OTHER" in n for n in report.notes)
    (tmp_path / "libnotinstalled_rt.dll").write_bytes(b"")
    assert inspect_dll(str(dll), models=("PERCBL",)).ok


def test_dll_inspection_rejects_32_bit_and_non_dlls(tmp_path):
    x86 = tmp_path / "x86.dll"
    x86.write_bytes(_tiny_dll(machine=0x14C, imports=()))
    assert "x86" in inspect_dll(str(x86)).problems[0]
    junk = tmp_path / "junk.dll"
    junk.write_bytes(b"hello")
    assert "not a Windows DLL" in inspect_dll(str(junk)).problems[0]


@pytest.mark.parametrize("line, code", [
    (" MODEL FOO NOT FOUND IN MODEL LIBRARY", "model_not_found"),
    (" INITIAL CONDITIONS SUSPECT:", "init_suspect"),
    ("forrtl: severe (157): Program Exception - access violation", "fortran_error"),
    (" NETWORK NOT CONVERGED AT TIME = 1.2", "network_not_converged"),
])
def test_log_patterns(line, code):
    assert [f.code for f in parse_log("junk\n" + line + "\nmore")] == [code]


def test_suspect_states_are_listed():
    log = " INITIAL CONDITIONS SUSPECT:\n  I  STATE  DSTATE\n  5  0.1  0.02\n\nlater"
    assert suspect_states(log) == ["I  STATE  DSTATE", "5  0.1  0.02"]
