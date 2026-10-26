"""The internal .outx reader, against files PSS/E 35.6 wrote and the values `dyntools` read from them.

The fixtures in tests/fixtures/outx/ each come with `<file>.truth.json.gz`: the ids and data that
`dyntools.CHNF.get_data()` returned for that exact file, so these tests need no PSS/E.
"""

import gzip
import json
import math
from pathlib import Path

import pytest

from blackbox.outx import MAGIC, OutxFormatError, read_outx

FIXTURES = Path(__file__).parent / "fixtures" / "outx"
FILES = ["4ch.outx", "10ch.outx", "nan_zero_pu_sag.outx", "psse367_4ch.outx"]  # the last one is PSS/E 36.7


def truth(name):
    with gzip.open(FIXTURES / (name + ".truth.json.gz"), "rt") as fh:
        return json.load(fh)


def same(a, b):
    """Equal, treating NaN as equal to NaN (PSS/E writes NaN for an unsolvable 0 pu bus)."""
    return len(a) == len(b) and all(x == y or (math.isnan(x) and math.isnan(y)) for x, y in zip(a, b))


@pytest.mark.parametrize("name", FILES)
def test_every_channel_and_sample_equals_dyntools(name):
    ref = truth(name)
    got = read_outx(FIXTURES / name)
    keys = [k for k in ref["ids"] if k != "time"]
    assert got.names == [ref["ids"][k] for k in keys]
    assert same(got.time, ref["data"]["time"])
    for key, column in zip(keys, got.names):
        assert same(got.column(column), ref["data"][key]), column


def test_channel_counts_and_title():
    got = read_outx(FIXTURES / "10ch.outx")
    assert got.names[:4] == ["V", "F", "P", "Q"] and len(got.names) == 10
    assert got.title == "BLACK-BOX VALIDATION / PLBVF1 SINGLE BUS"
    assert got.time[0] < 0 < got.time[-1]  # PSS/E writes two samples before t = 0


def test_nan_survives_the_read():
    got = read_outx(FIXTURES / "nan_zero_pu_sag.outx")
    assert any(math.isnan(x) for name in got.names for x in got.column(name))


def test_duplicate_identifiers_are_made_unique(tmp_path):
    blob = bytearray((FIXTURES / "4ch.outx").read_bytes())
    blob[3008 + 32:3008 + 33] = b"V"  # channel 2 now also called "V"
    blob[3008 + 33:3008 + 64] = b" " * 31
    path = tmp_path / "dup.outx"
    path.write_bytes(bytes(blob))
    assert read_outx(path).names == ["V", "V#2", "P", "Q"]


def test_a_header_without_data_is_reported_as_such(tmp_path):
    """What PSS/E wrote before the INTGAR(2) fix: a header and no records (148 bytes)."""
    path = tmp_path / "empty.outx"
    path.write_bytes(MAGIC + bytes(136))
    with pytest.raises(OutxFormatError, match="no data block"):
        read_outx(path)


def test_truncated_file_is_rejected_not_misread(tmp_path):
    blob = (FIXTURES / "4ch.outx").read_bytes()
    path = tmp_path / "cut.outx"
    path.write_bytes(blob[:-100])
    with pytest.raises(OutxFormatError):
        read_outx(path)


def test_wrong_file_type_is_rejected(tmp_path):
    path = tmp_path / "other.outx"
    path.write_bytes(b"not a channel file" * 100)
    with pytest.raises(OutxFormatError, match="wrong first bytes"):
        read_outx(path)


def test_unreadable_identifier_table_is_rejected(tmp_path):
    blob = bytearray((FIXTURES / "4ch.outx").read_bytes())
    blob[3008:3040] = bytes(range(1, 33))
    path = tmp_path / "names.outx"
    path.write_bytes(bytes(blob))
    with pytest.raises(OutxFormatError, match="not text"):
        read_outx(path)


def test_the_worker_reads_channel_files_with_the_internal_reader(monkeypatch):
    """The worker uses outx.py (staged beside it), and only falls back to dyntools for a file it cannot read."""
    import importlib.util

    root = Path(__file__).parent.parent / "src"
    spec = importlib.util.spec_from_file_location("psse_worker_under_test", root / "psse_worker" / "psse_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker.sys, "path", [str(root / "blackbox")] + list(worker.sys.path))
    data, reader = worker._read_outfile(str(FIXTURES / "4ch.outx"))
    assert reader == "internal" and list(data)[:2] == ["V", "F"] and len(data["time"]) == 487


# --- corrupted input: never a wrong answer, never an unexpected exception -------------------------------------------


def _consistent(got):
    return (len(set(got.names)) == len(got.names) and got.time
            and all(len(column) == len(got.time) for column in got.channels.values()))


@pytest.mark.parametrize("name", ["4ch.outx", "psse367_4ch.outx"])
def test_every_truncation_is_rejected_or_consistent(tmp_path, name):
    """Cut the file at many lengths: the reader either refuses or returns a self-consistent set, and nothing else."""
    blob = (FIXTURES / name).read_bytes()
    path = tmp_path / "cut.outx"
    for length in sorted({*range(0, 400, 7), *range(len(blob) - 120, len(blob))}):
        path.write_bytes(blob[:length])
        try:
            got = read_outx(path)
        except OutxFormatError:
            continue
        assert _consistent(got), length


@pytest.mark.parametrize("name", ["4ch.outx", "psse367_4ch.outx"])
def test_corrupting_single_bytes_never_raises_anything_else(tmp_path, name):
    import random

    blob = (FIXTURES / name).read_bytes()
    rng = random.Random(20261011)
    path = tmp_path / "flip.outx"
    for _ in range(400):
        data = bytearray(blob)
        for _ in range(rng.choice((1, 1, 2, 5))):
            data[rng.randrange(len(data))] = rng.randrange(256)
        path.write_bytes(bytes(data))
        try:
            got = read_outx(path)
        except OutxFormatError:
            continue
        assert _consistent(got)


def test_a_flipped_data_value_changes_only_that_value(tmp_path):
    """Damage inside the records is data, not structure: the file still reads and only that sample differs."""
    blob = bytearray((FIXTURES / "4ch.outx").read_bytes())
    clean = read_outx(FIXTURES / "4ch.outx")
    blob[3944 + 24 * 10 + 8:3944 + 24 * 10 + 12] = bytes.fromhex("0000803f")  # sample 10, channel 1 := 1.0
    path = tmp_path / "v.outx"
    path.write_bytes(bytes(blob))
    got = read_outx(path)
    assert got.time == clean.time and got.names == clean.names
    assert got.column("V")[10] == 1.0
    assert [i for i, (a, b) in enumerate(zip(got.column("V"), clean.column("V"))) if a != b] in ([10], [])


def test_a_file_from_a_future_layout_is_refused_with_a_reason(tmp_path):
    """Identifiers somewhere else (a layout this reader has not seen) must be refused, not read as garbage."""
    blob = bytearray((FIXTURES / "psse367_4ch.outx").read_bytes())
    blob[20:148] = b" " * 128  # blank the identifier table where 36.7 keeps it
    path = tmp_path / "moved.outx"
    path.write_bytes(bytes(blob))
    with pytest.raises(OutxFormatError, match="identifiers not found"):
        read_outx(path)


def test_a_real_36_7_file_with_nan_and_infinity_reads_where_dyntools_fails():
    """A 0 pu bus makes PERCxx1U write NaN and infinity. dyntools raises 'cannot convert float NaN to integer' on
    such a file (20 of 374 cases in the first 36.7 Standard run); the internal reader returns it as it is."""
    got = read_outx(FIXTURES / "psse367_nan_inf.outx")
    values = [x for name in got.names for x in got.column(name)]
    assert got.names == ["V", "F", "P", "Q"] and len(got.time) > 100
    assert any(math.isnan(x) or math.isinf(x) for x in values)
    assert all(math.isfinite(t) for t in got.time)  # the time axis itself is intact
