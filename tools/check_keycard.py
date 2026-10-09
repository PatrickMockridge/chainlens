#!/usr/bin/env python3
"""Read a keycard, report what it grants, and refuse one this library will not accept.

    python tools/check_keycard.py keycard.example.toml
    python tools/check_keycard.py keycard.toml --quiet

**What it is for.** A card is the data an answer rests on, and the values it does not state are
inherited from the shipped baseline. A holder who cannot see which of their values took effect
cannot tell their card from one that was silently ignored — so this prints the *resolved* card,
where every number is present, rather than the file, where some are missing.

**Why it is a separate tool rather than a mode of anything else.** `chainlens.keycard` is the
loader and does no I/O beyond the file it is handed; this is the part that talks to a terminal.
The library answers questions about chains, and a command that printed to stdout would be a
library that decided how a person's card ought to look.

Exit status is non-zero if the card is refused, so it is usable in a pre-commit hook.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chainlens.keycard import (
    SECTIONS,
    SHIPPED,
    Keycard,
    KeycardError,
    ResolvedThresholds,
    StatedVerbalScale,
    Thresholds,
    VerbalThresholds,
    load,
)

#: Printed so a holder can see which of their entries took effect and which were inherited. In
#: the card's own field order, because a reader comparing this against their file is reading both
#: in that order.
THRESHOLD_NAMES = tuple(Thresholds.model_fields)
VERBAL_NAMES = tuple(StatedVerbalScale.model_fields)


def describe(
    card: Keycard, path: Path, resolved: ResolvedThresholds, scale: VerbalThresholds
) -> str:
    """What the card grants, with every inherited value marked as inherited."""
    stated = card.thresholds.model_dump(exclude_none=True)
    stated_scale = card.verbal_scale.model_dump(exclude_none=True)
    effective = card.effective()
    lines = [
        f"{path}: schema_version {card.schema_version}",
        f"  keyholder: {card.effective().keyholder or '(none stated)'}",
        "  thresholds:",
    ]
    for name in THRESHOLD_NAMES:
        value = getattr(resolved, name)
        origin = "stated" if name in stated else f"inherited from {SHIPPED.keyholder}"
        lines.append(f"    {name:<20} {value!r:<22} ({origin})")
    # Reported beside the thresholds rather than folded into them: the card holds a *set* here,
    # and the boundaries are the ones a ratio is reported on, so a holder who cannot see which
    # took effect cannot tell their scale from one that was silently ignored.
    lines.append("  verbal_scale:")
    for name in VERBAL_NAMES:
        value = getattr(scale, name)
        origin = "stated" if name in stated_scale else f"inherited from {SHIPPED.keyholder}"
        lines.append(f"    {name:<20} {value!r:<22} ({origin})")
    lines.append(f"  labels: {len(card.labels)} asserted, {len(effective.labels)} effective")
    lines.extend(
        f"    {label.address}  {label.name}  <- {label.source}" for label in effective.labels
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("card", type=Path, help="the card to check")
    parser.add_argument("--quiet", action="store_true", help="only report problems")
    args = parser.parse_args(argv)

    if not args.card.exists():
        print(f"check_keycard: {args.card} does not exist", file=sys.stderr)
        return 1
    try:
        card = load(args.card)
    except KeycardError as exc:
        print(f"check_keycard: {exc}", file=sys.stderr)
        print(
            f"check_keycard: the sections a card may carry are {list(SECTIONS)}; see "
            f"keycard.example.toml for a template that validates",
            file=sys.stderr,
        )
        return 1

    # Resolved here rather than only inside `describe`, so that `--quiet` still exercises the door
    # a computation reaches the numbers through: a card that loaded but could not resolve would
    # otherwise fail in a run rather than in the check that exists for it.
    resolved = card.resolved_thresholds
    # The verbal scale is the one door that can refuse a card the loader accepted — a card whose
    # *merge* descends where the file did not — so it is resolved here too, and its refusal is
    # reported as a refusal rather than as a traceback.
    try:
        scale = card.resolved_verbal_scale
    except KeycardError as exc:
        print(f"check_keycard: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(describe(card, args.card, resolved, scale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
