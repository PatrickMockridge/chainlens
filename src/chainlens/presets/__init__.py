"""Presets: what a corpus is about, and what would confirm or refute it.

A corpus gives up addresses and numbers. A preset supplies the meaning — the terms a known event
ran on — and turns "here are some addresses" into "here is what this material claims, and here is
what would settle it".

See :mod:`chainlens.presets.records` for what a preset is and why it is not a label, and
:mod:`chainlens.presets.crowdsale` for the one that ships.
"""

from __future__ import annotations

from chainlens.presets.records import (
    DATA_DIR,
    CheckOutcome,
    CheckStatus,
    Preset,
    PresetError,
    PresetRow,
    RateTier,
    load_directory,
    load_file,
)

__all__ = [
    "DATA_DIR",
    "CheckOutcome",
    "CheckStatus",
    "Preset",
    "PresetError",
    "PresetRow",
    "RateTier",
    "load_directory",
    "load_file",
]
