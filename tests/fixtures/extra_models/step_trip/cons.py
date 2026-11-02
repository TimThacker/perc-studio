"""Step-trip CONs: one undervoltage and one overvoltage trip point."""

from __future__ import annotations

CON_NAMES = ("VUV", "TUV", "VOV", "TOV")

DEFAULT_CONS = {"VUV": 0.70, "TUV": 0.10, "VOV": 1.20, "TOV": 0.50}

DISPLAY_FIELDS = (
    ("VUV", "Undervoltage trip threshold (pu)", "VUV"),
    ("TUV", "Undervoltage trip delay (s)", "TUV"),
    ("VOV", "Overvoltage trip threshold (pu)", "VOV"),
    ("TOV", "Overvoltage trip delay (s)", "TOV"),
)


__all__ = [
    "CON_NAMES",
    "DEFAULT_CONS",
    "DISPLAY_FIELDS",
]
