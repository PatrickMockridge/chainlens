"""Reading a crowdsale table out of a corpus, and putting the preset's terms to it.

The material this serves is one screenshot of a spreadsheet: a bitcoin address, an ethereum address,
a vendor's label, and two numbers. Three questions can be put to a row like that, and only the first
needs nothing.

1. **rate** — the row's own two numbers imply an exchange rate, and the sale published its rates. A
   row at 2,000 ether per bitcoin is a purchase in the first fortnight; a row at no published rate
   is a question.
2. **allocation** — the ether was minted at genesis, so the address should hold exactly what the row
   says it received, in a record written before any of this. That is an *independent* fact, and the
   only one here strong enough to check the table against.
3. **funding** — the bitcoin should have gone to the address the sale collected into. This is the
   one check that is a transaction lookup, and it is on the paying chain rather than the
   issuing one.

**Why the row is read this way, and how fragile that is.** The transcription preserves the table's
rows as lines, so a row is a line — which is a fact about the material rather than a convenience.
Within a line the two addresses are the first address of each family and the amounts are the *last
two numbers*, because every row of this table ends with "what was paid, what was issued". That is a
rule fitted to this table, and it is stated here rather than buried: a table whose columns are
ordered differently would parse wrongly and silently. The rate check is what catches that, because a
misread column produces a rate that matches no published tier.

**What this does not do.** It does not decide whether a row is *true* — it compares a row to
published terms. A row that matches every check is a row consistent with the sale; a row that
matches none is worth reading the image for. Neither is a finding about who owned what.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from chainlens.models.enums import Chain
from chainlens.notes.addresses import address_mentions
from chainlens.notes.corpus import Corpus
from chainlens.presets.records import CheckOutcome, CheckStatus, Preset, PresetRow

__all__ = ["allocation_from", "check_allocation", "check_rate", "rows_in", "summarise"]

#: A number as a table renders one: grouped thousands and a decimal, no sign and no units. Narrow
#: on purpose — a pattern that also caught verdict words or percentages would feed the checks
#: numbers the row never stated.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: How many of a row's trailing numbers to take as (paid, issued). Two, and the reason is the
#: column layout rather than a preference — see the module docstring.
_TRAILING = 2


def rows_in(corpus: Corpus, preset: Preset, *, note: str | None = None) -> tuple[PresetRow, ...]:
    """Every row of a corpus that carries the shape this preset describes.

    **A row of this table is paid from a bitcoin address, and the issued column is either an
    ethereum address or the word ``unknown``.** Both conditions are needed and each was measured:
    requiring only an ethereum address and two numbers matched twenty-three rows of a *mining* table
    whose block heights read exactly like amounts, and requiring only a bitcoin address matched a
    sentence of prose that happened to hold two of them.

    The cost of the bitcoin condition is stated rather than hidden: **rows whose bitcoin address was
    garbled in transcription are not recognised at all**, even when their ethereum address is
    intact. Those addresses are still found by ``chainlens notes --addresses`` and can be put to the
    allocation check on their own — they are just not rows.

    Only lines that qualify are returned. A line missing one half is not a partial row to be
    reported as unreadable; it is a line of a different shape, and the corpus holds a great many of
    those.

    **The addresses come from the library's validator, not from a pattern written here.** An earlier
    version of this function matched them with its own regex, and built a row anchored to an address
    the identifier check had *already flagged as garbled* — the transcription of the very table this
    serves had dropped a character from the crowdsale address, so the totals row was quietly tied to
    an address that is not the one the sale collected into. A local pattern re-introduces exactly
    the failure the check exists to prevent. Using
    :func:`~chainlens.notes.addresses.address_mentions` means a row can only be built on an address
    that could be looked up.
    """
    rows: list[PresetRow] = []
    for item in corpus.readable:
        if note is not None and item.path != note:
            continue
        on_note = [
            mention
            for mention in address_mentions(corpus)
            if mention.usable and mention.note == item.path
        ]
        lines = item.text.splitlines()
        for index, line in enumerate(lines):
            on_line = sorted(
                (m for m in on_note if _line_of(item.text, m.position) == index),
                key=lambda m: m.position,
            )
            payer = next((m for m in on_line if m.chain is Chain.BITCOIN), None)
            issuer = next((m for m in on_line if m.chain is Chain.ETHEREUM), None)
            numbers = _NUMBER.findall(line)
            if payer is None:
                # A row of this table is *paid from* somewhere. Without that side it is not a row
                # of the sale, and this is the test that keeps the other screenshots out — a
                # mining table's rows carry an ethereum address and a row of block numbers, and
                # read as sale rows without it. Measured: dropping this condition took the
                # recognised set from 8 rows to 31, the extra 23 being block heights.
                continue
            if issuer is None and not _says_unknown(line):
                # The issued column is either an address or the word the table uses for a
                # participant who never claimed one. Anything else in that position is a different
                # table.
                continue
            paid_text, issued_text = _trailing_amounts(numbers)
            start = _line_start(item.text, index)
            anchor = payer or issuer
            assert anchor is not None  # one of the two is present, checked above
            rows.append(
                PresetRow(
                    note=item.path,
                    line=index,
                    text=line.strip(),
                    paid_address=payer.address if payer else None,
                    issued_address=issuer.address if issuer else None,
                    paid_text=paid_text,
                    issued_text=issued_text,
                    account=_label_between(
                        line,
                        (payer.position - start) if payer else 0,
                        (issuer.position - start) if issuer else len(line),
                    ),
                    # The event's own totals row pays into the address the event collected into.
                    # See `PresetRow.is_summary` for why this is the signal and an absent issued
                    # address is not.
                    summary=preset.funding_address is not None
                    and payer is not None
                    and payer.address == preset.funding_address,
                )
            )
    return tuple(rows)


def _says_unknown(line: str) -> bool:
    """Whether the row's issued column reads ``unknown`` — this table's word for an unclaimed
    allocation.

    A marker rather than a heuristic: the corpus's table writes it, and a row carrying it is a row
    of the sale with no address to allocate to, which is a fact worth keeping rather than a line to
    skip."""
    return "unknown" in line.lower()


def _line_of(text: str, position: int) -> int:
    """Which line a character offset falls on."""
    return text.count("\n", 0, position)


def _line_start(text: str, index: int) -> int:
    """The offset the given line begins at."""
    cursor = 0
    for _ in range(index):
        cursor = text.index("\n", cursor) + 1
    return cursor


def check_rate(row: PresetRow, preset: Preset) -> CheckOutcome:
    """Whether the row's own two numbers imply a rate the sale published.

    The row is checked against itself, so this needs no network and no dataset — which is why it is
    the first thing to run over material that has not been identified yet.
    """
    if not preset.rates:
        return CheckOutcome(
            check="rate",
            status=CheckStatus.NOT_ASKABLE,
            detail=f"preset {preset.name!r} publishes no rates, so there is nothing to compare to",
        )
    implied = row.implied_rate
    if implied is None:
        return CheckOutcome(
            check="rate",
            status=CheckStatus.NOT_ASKABLE,
            detail=(
                f"the row's amounts could not both be read as numbers ({row.paid_text!r}, "
                f"{row.issued_text!r}), so no rate can be derived from it"
            ),
        )
    if row.is_summary:
        return CheckOutcome(
            check="rate",
            status=CheckStatus.NOT_ASKABLE,
            detail=(
                f"this row reports totals: its implied rate of {implied:,.2f} blends every tier "
                "the sale ran at, so it matches none and that is not a finding"
            ),
            values={"implied": implied},
        )
    tier = preset.rate_for(implied)
    if tier is None:
        return CheckOutcome(
            check="rate",
            status=CheckStatus.UNMATCHED,
            detail=(
                f"the row implies {implied:,.2f} per bitcoin, which is no rate this sale "
                f"published ({', '.join(f'{t.rate:,.0f}' for t in preset.rates)}). Worth reading "
                "the image: a misread column produces exactly this"
            ),
            values={"implied": implied},
        )
    return CheckOutcome(
        check="rate",
        status=CheckStatus.MATCHED,
        detail=f"the row implies {implied:,.2f} per bitcoin — {tier.note or 'a published rate'}",
        values={"implied": implied, "tier": tier.rate},
    )


def check_allocation(
    row: PresetRow, *, allocation: Mapping[str, int] | None = None
) -> CheckOutcome:
    """Whether an independent record holds what the row says the address received.

    ``allocation`` maps a lowercase address to an amount in the issued asset's smallest unit. When
    it is absent the check says so rather than passing quietly: "not checked" and "checked and
    agreed" are the two things a reader most needs to tell apart, and a check that defaulted to
    agreement would make the whole report worthless.
    """
    if row.issued_address is None:
        return CheckOutcome(
            check="allocation",
            status=CheckStatus.NOT_ASKABLE,
            detail="the row names no address on the issuing chain, so there is nothing to look up",
        )
    if allocation is None:
        return CheckOutcome(
            check="allocation",
            status=CheckStatus.NOT_CHECKED,
            detail=(
                "no allocation record was supplied, so the row was not checked against one. Pass "
                "the genesis allocation to ask this question"
            ),
            values={"address": row.issued_address, "claimed": row.issued_text},
        )
    # **The record is in wei and the row is in ether, and comparing them directly was wrong.**
    # The allocation file renders every balance as base units, which is right for a record and
    # useless as a number to show a reader; the row is written in ether because that is how the
    # table writes it. Converted here, once, rather than asking either side to change.
    held_wei = allocation.get(row.issued_address.lower())
    held = held_wei / 10**18 if held_wei is not None else None
    claimed = _as_ether(row.issued_text)
    if held is None:
        return CheckOutcome(
            check="allocation",
            status=CheckStatus.UNMATCHED,
            detail=(
                f"the record holds no allocation for {row.issued_address}. Either the address was "
                "misread or it was not a sale participant"
            ),
            values={"address": row.issued_address},
        )
    if claimed is None:
        return CheckOutcome(
            check="allocation",
            status=CheckStatus.NOT_ASKABLE,
            detail=f"the row's issued amount {row.issued_text!r} could not be read as a number",
            values={"address": row.issued_address},
        )
    if abs(held - claimed) > 1.0:
        return CheckOutcome(
            check="allocation",
            status=CheckStatus.UNMATCHED,
            detail=(
                f"the record holds {held:,.0f} and the row says {claimed:,.0f} — the difference is "
                f"{held - claimed:,.0f}"
            ),
            values={"address": row.issued_address, "held": held, "claimed": claimed},
        )
    return CheckOutcome(
        check="allocation",
        status=CheckStatus.MATCHED,
        detail=f"the record holds exactly what the row says: {held:,.0f}",
        values={"address": row.issued_address, "held": held},
    )


def allocation_from(path: Path, *, key: str = "accounts") -> Mapping[str, int]:
    """A genesis allocation file, as ``{lowercase address: wei}``.

    Reads the shape the two client implementations publish — a mapping under ``accounts`` (or
    ``alloc``) of address to either ``{"balance": "0x…"}`` or a bare amount. Addresses are keyed
    lowercase because the row's are, and the file's are checksummed.

    Raises:
        ValueError: the file does not hold an allocation this can read. Loud rather than empty,
            because an empty mapping is indistinguishable from a working check that found nothing.
    """
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    accounts = payload.get(key) or payload.get("alloc") or payload
    if not isinstance(accounts, Mapping) or not accounts:
        raise ValueError(f"{path}: no allocation found under {key!r}")
    out: dict[str, int] = {}
    for address, entry in accounts.items():
        if not isinstance(address, str) or not address.startswith("0x"):
            # A builtin contract or a metadata key, not an allocation.
            continue
        balance = entry.get("balance") if isinstance(entry, Mapping) else entry
        if balance is None:
            continue
        try:
            out[address.lower()] = int(balance, 16) if isinstance(balance, str) else int(balance)
        except (TypeError, ValueError):
            continue
    if not out:
        raise ValueError(f"{path}: no allocation found — the file held no address balances")
    return out


def summarise(rows: Sequence[PresetRow], outcomes: Sequence[Sequence[CheckOutcome]]) -> str:
    """One line: how many rows, and how the checks came out."""
    flat = [outcome for group in outcomes for outcome in group]
    counts: dict[str, int] = {}
    for outcome in flat:
        counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1
    parts = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    return f"{len(rows)} row(s); checks: {parts}"


def _trailing_amounts(numbers: Sequence[str]) -> tuple[str, str]:
    """The last two numbers on a row, as (paid, issued). See the module docstring for why."""
    if len(numbers) < _TRAILING:
        return "", ""
    return numbers[-2], numbers[-1]


def _label_between(line: str, start: int, end: int) -> str:
    """Whatever the row says between its two addresses — a vendor's column, usually.

    Collapsed and clipped, because it is for a reader looking at the report beside the screenshot
    rather than for anything downstream.
    """
    return " ".join(line[start:end].split())[:60]


def _as_ether(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None
