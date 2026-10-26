"""Reader for PSS/E extended channel output files (`.outx`), so a validation run's
traces can be loaded, listed by channel and plotted without PSS/E or `dyntools`.

Why not `dyntools`: it needs PSS/E's own DLLs, the matching `PSSPY` folder and a
PATH set up exactly right, and when any of that is missing it fails with an
unrelated `NameError`. This
reader needs nothing but the file.

The `.outx` layout is not documented by PSS/E. What is read here was worked out
from files written by PSS/E 35.6 and 36.7 and checked against `dyntools` (the
evidence is in the PSS/E validation library, which is not published). Only two things are read:

* the **data block**: one record per saved time step, each `[n, time, ch1..chn]`
  as little-endian float32, where `n` is the channel count stored as a float. The
  block ends 8 bytes before the end of the file. It is found by arithmetic alone
  (whole records from a start that carries n, with the same n at the first, second
  and last record), so a file that does not fit is rejected instead of misread;
* the **channel identifiers**: `n` consecutive 32-byte space-padded fields, at
  byte 20 (36.7) or byte 3008 (35.6).

Anything that does not check out raises `OutxFormatError` with what was expected.
The caller (the worker) falls back to `dyntools`, so an unrecognized layout, for
example from another PSS/E version, costs nothing but the fallback.
"""

from __future__ import annotations

import math
import sys
from array import array
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = b"FuP_pHySPCD%"
TRAILER_BYTES = 8
IDENT_BYTES = 32
# Where the first channel identifier sits, by the PSS/E version that wrote the file (tried in order). 35.6 has a
# long header of tables in front of it; 36.7 has just the magic and two words.
NAMES_OFFSETS = (20, 3008)
TITLE_LINES = 2  # the two 60-character title lines that follow the identifier table
TITLE_BYTES = 60
MAX_CHANNELS = 4096  # sanity bound; PSS/E's own limit is lower
CHECKED_RECORDS = 3  # records whose leading channel count is verified (first, second, last)


class OutxFormatError(ValueError):
    """The file is not an .outx this reader can interpret (message says why)."""


@dataclass
class ChannelFile:
    """The decoded file: a time axis and named channels of equal length."""

    path: str
    title: str
    time: list[float]
    channels: dict[str, list[float]] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return list(self.channels)

    def column(self, name: str) -> list[float]:
        return self.channels[name]


def _floats(raw: bytes) -> array:
    values = array("f")
    values.frombytes(raw)
    if sys.byteorder == "big":
        values.byteswap()
    return values


def _int_at(blob: bytes, offset: int) -> int:
    return int.from_bytes(blob[offset:offset + 4], "little", signed=True)


def _anchored(blob: bytes, start: int, n: int, samples: int) -> bool:
    """Does the candidate block sit where PSS/E puts it? Either right after the identifier and title lines
    (36.7), or behind a word holding samples * (n + 2) + 2 (35.6). Without this, the last few values of a
    truncated file can pass for a one-channel, one-sample block."""
    after_titles = NAMES_OFFSETS[0] + n * IDENT_BYTES + TITLE_LINES * TITLE_BYTES
    return start == after_titles or _int_at(blob, start - 4) == samples * (n + 2) + 2


def _find_data_block(blob: bytes) -> tuple[int, int, int]:
    """(offset of the first record, channels, samples), from the arithmetic alone.

    A candidate start `p` holds the float n (the channel count). The block then runs to
    TRAILER_BYTES before the end of the file in whole records of (n + 2) words, and the first, second
    and last record each start with the same n and carry finite, non-decreasing times, and the block sits
    where PSS/E puts it (`_anchored`).
    """
    size = len(blob)
    for p in range(len(MAGIC), size - 16, 4):
        n_float = _floats(blob[p:p + 4])[0]
        n = int(n_float) if math.isfinite(n_float) and abs(n_float) < MAX_CHANNELS + 1 else 0
        if n != n_float or n < 1:
            continue
        record = (n + 2) * 4
        span = size - TRAILER_BYTES - p
        if span <= 0 or span % record:
            continue
        samples = span // record
        starts = sorted({0, min(1, samples - 1), samples - 1})
        heads = [_floats(blob[p + i * record:p + i * record + 8]) for i in starts]
        times = [h[1] for h in heads]
        same_count = all(h[0] == n for h in heads)
        sane_times = all(math.isfinite(t) for t in times) and times == sorted(times)
        if same_count and sane_times and _anchored(blob, p, n, samples):
            return p, n, samples
    raise OutxFormatError("no data block found: the file has a header but no time-step records "
                          "(PSS/E was probably told to record no channels)")


def _identifiers(blob: bytes, n: int, data_start: int) -> tuple[list[str], int]:
    """(identifiers, offset of the table): the first known table offset where n readable names sit."""
    problems = []
    for offset in NAMES_OFFSETS:
        end = offset + n * IDENT_BYTES
        if end > data_start:
            problems.append(f"no room for {n} identifiers at byte {offset}")
            continue
        names = []
        for i in range(n):
            text = blob[offset + i * IDENT_BYTES:offset + (i + 1) * IDENT_BYTES].decode("latin-1")
            if not all(" " <= c <= "~" for c in text) or not text.strip():
                problems.append(f"identifier {i + 1} at byte {offset + i * IDENT_BYTES} is not text")
                break
            names.append(text.strip())
        else:
            return names, offset
    raise OutxFormatError("channel identifiers not found where this reader knows to look (" + "; ".join(problems)
                          + "); this PSS/E version may lay the header out differently")


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return out


def _title(blob: bytes, offset: int) -> str:
    lines = []
    for i in range(TITLE_LINES):
        start = offset + i * TITLE_BYTES
        text = blob[start:start + TITLE_BYTES].decode("latin-1", errors="replace")
        text = "".join(c if " " <= c <= "~" else " " for c in text).strip()
        if text:
            lines.append(text)
    return " / ".join(lines)


def read_outx(path: str | Path) -> ChannelFile:
    """Decode a PSS/E 35/36 extended channel output file."""
    path = Path(path)
    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        raise OutxFormatError(f"{path.name} is not an extended channel output file (.outx): wrong first bytes")
    start, n, samples = _find_data_block(blob)
    names, table = _identifiers(blob, n, start)
    names = _unique(names)
    words = _floats(blob[start:start + samples * (n + 2) * 4])
    stride = n + 2
    time = [float(words[r * stride + 1]) for r in range(samples)]
    channels = {name: [float(words[r * stride + 2 + c]) for r in range(samples)] for c, name in enumerate(names)}
    return ChannelFile(str(path), _title(blob, table + n * IDENT_BYTES), time, channels)
