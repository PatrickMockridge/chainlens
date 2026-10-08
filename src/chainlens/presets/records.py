"""A preset: a known event, its known terms, and the datasets that make it checkable.

A corpus of screenshots tells you some addresses and some numbers. What it cannot tell you is what
they *mean* — whether a row is a payment, an allocation, a balance, or a summary, and therefore what
would confirm or refute it. That is domain knowledge, and a preset is where it is written down.

**Why this is not a label.** A label says *this address is that* (see
:mod:`chainlens.labels.records`), and it is checked by looking the address up. A preset says *this
event had these terms*, and it is checked by applying them to the material — a rate, a schedule, an
allocation table. The two are different shapes of assertion and they fail differently: a label is a
flat claim about an address, a preset is a rule that a row either satisfies or does not.

**What makes a preset worth having is that it turns an unanswerable question into an answerable
one.** The corpus this was written for carries an Ethereum crowdsale table: a bitcoin address, an
ethereum address, and two numbers. The obvious check — *is there a transaction between those two
addresses?* — can never succeed, and not because the data is missing: **the ether was minted at
genesis, so there is no payment to find.** Every attempt to corroborate that table as a transfer
would have manufactured a false negative on the best evidence in the corpus. The preset replaces
that with three questions the material can actually answer.

**A preset is deliberately not a wire document.** Nothing downstream should be able to mistake a
preset's output for a finding about the chain: it is a report a person reads, and each check says
what it asked and what came back.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel
from chainlens.models.enums import Chain

if TYPE_CHECKING:  # the card imports this module for `Preset`, so the edge runs one way only
    from chainlens.keycard import Keycard

__all__ = [
    "DATA_DIR",
    "CheckOutcome",
    "Preset",
    "PresetError",
    "PresetRow",
    "RateTier",
    "load_directory",
    "load_file",
    "load_named",
]

#: The presets this package ships.
DATA_DIR = Path(__file__).parent / "data"


class CheckStatus(StrEnum):
    """What a check can come back as.

    **There is no `REFUTED` member**, and that is a finding about the method rather than an
    omission. A preset's checks compare a row to a *published* fact, and a row that does not match
    may be a transcription error, a later amendment, or a misreading of which column held what —
    none of which is the chain contradicting anything. ``UNMATCHED`` says that and sends a reader
    back to the image; a status that claimed refutation would not have earned it.
    """

    MATCHED = "matched"
    #: The row does not agree with the published terms. Worth a look, not a refutation.
    UNMATCHED = "unmatched"
    #: The check needs something this row or this run does not have.
    NOT_ASKABLE = "not_askable"
    #: The check exists and nobody supplied the data it needs.
    NOT_CHECKED = "not_checked"


class PresetError(ChainlensError):
    """A preset file, or one entry in it, is not usable."""


class RateTier(LensModel):
    """One published exchange rate, and the window it applied to.

    Attributes:
        rate: ether per bitcoin.
        note: which part of the sale this was, in words. A reader checking a row needs to know
            that 2,000 was the opening rate and 1,337 a late one, because a row at either is a
            different fact about when somebody bought.
    """

    rate: float = Field(gt=0)
    note: str = ""


class Preset(LensModel):
    """A known event and the terms it ran on.

    Attributes:
        name: how the preset is named on the command line.
        description: what the event was, for a reader who has not met it.
        chain: the chain the *issued* asset lives on — the one a row's allocation is checked
            against. A preset may involve another chain (the crowdsale was paid in bitcoin) and
            that is what :attr:`funding_address` is for.
        source: a URL where the terms can be read. Required, for the reason a label's is: a rule
            nobody can check is indistinguishable from an invention.
        funding_address: where the asset was *paid in*, when the event took that shape. Optional,
            because not every event has one.
        rates: the published exchange rates, when the event had a rate at all.
        allocation_dataset: what independent record the issued amounts can be checked against, in
            words — the URL of the file a caller should supply. Not fetched here; see
            :mod:`chainlens.presets.crowdsale`.
        notes: anything a reader needs in order not to over-rate the checks.
    """

    name: str = Field(min_length=1)
    description: str = ""
    chain: Chain
    source: str
    funding_address: str | None = None
    rates: tuple[RateTier, ...] = ()
    allocation_dataset: str | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _the_source_is_a_url(self) -> Preset:
        if not self.source.startswith(("http://", "https://")):
            raise ValueError(
                f"preset {self.name!r}: source must be an http(s) URL, not {self.source!r} — a "
                "rule nobody can read is indistinguishable from an invention"
            )
        return self

    def rate_for(self, implied: float, *, tolerance: float = 0.01) -> RateTier | None:
        """The published tier an implied rate matches, or ``None``.

        Compared with a relative tolerance rather than exactly, because a row's two numbers are
        transcribed from an image and a rate is derived from them: ``157.40392`` bitcoin against
        ``314,808`` ether implies 1999.999…, which is the 2,000 tier and not a near miss.

        Tolerance is relative and small on purpose. A wide window would make the check pass on a
        rate that is merely close, which is the opposite of what it is for — the rows in this
        corpus that do *not* match a tier are the interesting ones.
        """
        for tier in self.rates:
            if abs(implied - tier.rate) <= tier.rate * tolerance:
                return tier
        return None


class PresetRow(LensModel):
    """One row of a corpus that the preset recognised, and what it said.

    Attributes:
        note: which note the row was read from.
        line: the row's number in the note, so a reader can find it in the transcription.
        text: the row as transcribed, so a reader can compare it to the screenshot.
        paid_address: the address the asset was paid *from*, when the row names one.
        issued_address: the address the allocated asset belongs to, when the row names one.
        paid: how much was paid, in the funding asset's smallest unit.
        issued: how much was allocated.
        paid_text: the paid amount as written, so a reader can see what was parsed.
        issued_text: the issued amount as written.
        account: the row's label, when the transcription carried one — a vendor's column, usually.
    """

    note: str
    line: int
    text: str
    paid_address: str | None = None
    issued_address: str | None = None
    paid_text: str = ""
    issued_text: str = ""
    account: str = ""

    @property
    def implied_rate(self) -> float | None:
        """Ether per bitcoin, as the row's own two numbers imply it."""
        paid, issued = _amount(self.paid_text), _amount(self.issued_text)
        if paid is None or issued is None or paid == 0:
            return None
        return issued / paid

    @property
    def is_summary(self) -> bool:
        """Whether the row reports the event's totals rather than one participant's purchase.

        **The signal is the row's own funding address, and getting this wrong cost a round.** A
        total's implied rate blends every tier, so it matches none and must not be reported as a
        failure. The first rule used here was "the row names no address on the issuing chain", which
        is *not* the same fact: a participant row whose issued column reads "unknown" is still a
        purchase with a perfectly checkable rate, and the rule silently skipped four of them. A
        second reading of the data made the real signal plain — the totals row pays *into the
        address the event collected into*, because it is the event's own summary.

        Set by :func:`chainlens.presets.crowdsale.rows_in`, which is where the preset is in hand.
        """
        return self.summary

    #: Whether the preset's own funding address appears as this row's payer.
    summary: bool = False


class CheckOutcome(LensModel):
    """What one check asked, and what came back.

    Attributes:
        check: which check — ``rate``, ``allocation``, ``funding``.
        status: one of ``matched``, ``unmatched``, ``not_askable``, ``not_checked``.
        detail: the sentence a reader gets. Always present, because "unmatched" without a reason is
            a number a reader cannot act on.
        values: whatever the check compared, for a reader who wants to see the arithmetic.
    """

    check: str
    status: CheckStatus
    detail: str
    values: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def is_settled(self) -> bool:
        """Whether the check said anything at all, as opposed to not being askable."""
        return self.status in (CheckStatus.MATCHED, CheckStatus.UNMATCHED)

    def format(self) -> str:
        return f"{self.check}: {self.status.value} — {self.detail}"


def _amount(text: str) -> float | None:
    """A written amount as a number, or ``None``.

    Commas are grouping and are dropped; everything else has to be a plain decimal. This is
    deliberately narrow — a parser that guessed at ``~40k`` would put a number into a check that the
    material never stated, and the check would then be about the parser.
    """
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def load_named(name: str, *, card: Keycard | None = None) -> Preset:
    """A preset by name: the card's if it states terms for that event, else the shipped one.

    **The precedence every other card lookup follows**, and the reason a card carries presets in
    the first place: a holder who knows the terms of an event should not have to put a YAML file
    somewhere the library looks, nor should the library need a second shape for a user's terms. A
    card's preset *is* a `Preset`, so the rules — a citable source, tiers that increase — are
    enforced once.

    Raises:
        PresetError: neither the card nor the shipped data names that event. The message lists
            what is available, because "no such preset" without a list is a dead end.
    """
    # `Keycard` is only an annotation here, so it is quoted rather than imported.
    # Imported here rather than at the top of the file, and that is a cycle and not a
    # preference: `chainlens.keycard` imports *this* module for `Preset`, so the edge has to run
    # one way. A module-level import would make the two unimportable in either order.
    from chainlens.keycard import SHIPPED

    if card is not None:
        found = card.preset(name)
        if found is not None:
            return found
    shipped = next(
        (preset for preset in SHIPPED.presets if preset.name == name),
        None,
    )
    if shipped is not None:
        return shipped
    raise PresetError(
        f"no preset named {name!r}; the shipped ones are "
        f"{sorted(preset.name for preset in SHIPPED.presets)}"
    )


def _yaml() -> Any:
    """The YAML parser, imported where it is used rather than where this module is.

    **A module-level `import yaml` on this module was a real regression once**, and the shape of
    the failure is worth keeping: `chainlens.keycard` imports this module for `Preset`, so with
    the import at the top, `chainlens ui --help` in a clean install died with
    ``ModuleNotFoundError: No module named 'yaml'`` — a *dev-only* dependency made load-bearing on
    a path that never reads a YAML file. It was caught by CI's clean-wheel step and not by the
    suite, because in a development environment PyYAML is installed.

    It is a function-local import for the reason the rest of this library does the same for `PIL`
    and `anthropic`: an optional dependency belongs where it is used. ``chainlens[presets]``
    declares it, and the message below names that, because a bare `ModuleNotFoundError` from four
    frames down is not a thing a user can act on.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - the extra is installed in this environment
        raise PresetError(
            "reading a preset from YAML needs PyYAML, which is not a core dependency; install "
            "chainlens[presets], or use `load_named` — the shipped presets are in the keycard and "
            "need no YAML parser"
        ) from exc
    return yaml


def load_file(path: Path) -> Preset:
    """One preset from a YAML file.

    Raises:
        PresetError: the file is unreadable or does not describe a preset.
    """
    yaml = _yaml()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PresetError(f"{path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise PresetError(f"{path}: expected a mapping, got {type(raw).__name__}")
    try:
        return Preset.model_validate(raw)
    except ValueError as exc:
        raise PresetError(f"{path}: {exc}") from exc


def load_directory(directory: Path | None = None) -> Iterator[Preset]:
    """Every preset in a directory, by filename. Defaults to the ones this package ships."""
    root = directory if directory is not None else DATA_DIR
    for path in sorted(root.glob("*.yaml")):
        yield load_file(path)
