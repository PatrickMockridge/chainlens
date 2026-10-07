"""Turning a screenshot's label column into a label file, honestly.

A corpus of screenshots often carries a table somebody published: an address, the name a vendor
gives it, sometimes an amount. That is a *source asserting* something, which is exactly what a
:class:`~chainlens.labels.records.LabelRecord` is for — and the point of doing this rather than
reading the table by eye is that the assertions then merge with everything else the label layer
knows, each carrying its own provenance.

**The format's invariants are satisfied, not relaxed.** Three of them bite here and each is the
reason a field exists:

* ``source`` must be an http(s) URL. A screenshot has none, so the caller must supply the page the
  assertion is readable at — the vendor's published table, or the explorer page for an Etherscan
  screenshot. There is no default: a label nobody can check is indistinguishable from a guess, and
  inventing a URL to make the format accept one would defeat the field.
* ``corroboration`` must cover every address. So the ingest looks each one up and records what the
  chain showed, rather than writing the vendor's numbers down as if they were observations. The
  ``is_contract`` answer is the useful one on an account chain: it is how a named multisig or token
  contract is told from an address merely typed into a table.
* **a truncated address produces nothing.** Most addresses on a screenshot of an explorer page are
  prefixes — the page abbreviated them — and a prefix cannot be looked up, so it cannot be
  corroborated, so it cannot become a record. It is reported by name instead. Completing it, or
  matching it by prefix, would manufacture an assertion the source never made.

**Identity is the thing to be careful about.** A vendor naming a person is doing identity
inference, and this library does not. What it does is record the assertion *as that vendor's*, with
the vendor named in ``provider``, the category in ``kind``, and a note saying what the record is
and is not. ``check_label`` already reports a label's name, source and kind separately and already
carries the caveat that a label is *"an attribution by a third party, recorded here with its source
so it can be weighed rather than trusted"* — so nothing in the checker changes. What changes is that
the ingest must populate those fields honestly rather than collapsing them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from chainlens.exceptions import ChainlensError
from chainlens.labels.records import Corroboration, LabelFile, LabelRecord
from chainlens.models.enums import EntityKind, LabelSource
from chainlens.notes.addresses import AddressMention
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability

__all__ = ["IngestReport", "ingest_labels"]


class IngestReport:
    """What an ingest produced, and what it refused to.

    A plain class rather than a model: it is a return value for a command, not an artifact that
    travels, and giving it a serialised shape would be a second contract to keep for nothing.

    Attributes:
        file: the label file, or ``None`` when nothing could be corroborated.
        skipped: addresses that could not become records, each with the reason.
    """

    def __init__(
        self, *, file: LabelFile | None, skipped: tuple[tuple[str, str], ...] = ()
    ) -> None:
        self.file = file
        self.skipped = skipped

    @property
    def kept(self) -> int:
        return len(self.file.labels) if self.file is not None else 0

    @property
    def addresses(self) -> int:
        if self.file is None:
            return 0
        return sum(len(record.addresses) for record in self.file.labels)

    def format(self) -> str:
        line = f"{self.kept} label record(s), {self.addresses} address(es) corroborated"
        if self.skipped:
            line += f"; {len(self.skipped)} address(es) could not be looked up"
        return line


async def ingest_labels(
    mentions: Sequence[AddressMention],
    *,
    provider: Provider,
    name: str,
    source: str,
    kind: EntityKind,
    licence: str,
    description: str = "",
    note: str | None = None,
) -> IngestReport:
    """Build a label file from what a corpus says about its usable addresses.

    Every address in ``mentions`` that is usable is looked up and gets one record naming ``name``,
    asserted by ``name`` at ``source``. Mentions that are not usable are reported in
    :attr:`IngestReport.skipped` rather than dropped silently — the count is the honest answer to
    "how much of this table could be checked".

    Args:
        mentions: what the corpus held. Only the usable ones become records.
        provider: the chain provider the corroboration is drawn from.
        name: what the source calls this — the identity the *source* asserts. Recorded as the
            source's assertion, never as an established fact.
        source: a URL where the assertion can be read. Required; the format refuses one without.
        kind: the category the source puts it in.
        licence: what this file's data may be redistributed under. Required, because the format
            requires it of every file: "no licence stated" and "any licence" are different claims
            and only the caller knows which they mean.
        description: what the file is, for a reader.
        note: appended to every record's note, for anything the source's own framing needs.

    Raises:
        ChainlensError: the provider cannot read balances or addresses, so nothing could be
            corroborated — in which case the format would refuse every record anyway, and saying
            so once beats forty identical failures inside a model validator.
    """
    usable = [mention for mention in mentions if mention.usable and mention.address]
    skipped = tuple(
        (mention.as_written, mention.because or "not usable")
        for mention in mentions
        if not mention.usable
    )
    if not usable:
        return IngestReport(file=None, skipped=skipped)
    if not provider.supports(Capability.ADDRESS):
        raise ChainlensError(
            f"provider {provider.name!r} cannot read an address, so nothing here can be "
            "corroborated — and a label record refuses to exist without a corroboration. "
            "Configure a provider that can"
        )

    observed: dict[str, Corroboration] = {}
    for mention in usable:
        assert mention.address is not None  # narrowed by `usable`, asserted for the checker
        observation = await _corroborate(provider, mention.address, note=note)
        if observation is not None:
            observed[mention.address] = observation

    if not observed:
        return IngestReport(file=None, skipped=skipped)

    record = LabelRecord(
        name=name,
        kind=kind,
        addresses=tuple(observed),
        source=source,
        corroboration=observed,
        note=note,
    )
    return IngestReport(
        file=LabelFile(
            provider=name,
            source_kind=LabelSource.USER,
            licence=licence,
            description=description or f"asserted by {name}",
            labels=(record,),
        ),
        skipped=skipped,
    )


async def _corroborate(
    provider: Provider, address: str, *, note: str | None
) -> Corroboration | None:
    """What the chain shows about one address, or ``None`` when it could not be read.

    ``None`` rather than an empty corroboration: the record's validator requires a corroboration
    per address and the honest answer to "the lookup failed" is to leave the address out of the
    record, not to write a record with no observation behind it.

    The balance is left as the chain's own integer rather than rendered to a decimal, because the
    record stores floats for display and a wei-scale integer does not survive one — a balance
    rendered wrong is worse than a balance not rendered.
    """
    try:
        address_view = await provider.get_address(address)
    except ChainlensError:
        return None
    balance = await _balance(provider, address)
    return Corroboration(
        chain=provider.chain,
        observed_at=datetime.now(UTC).date(),
        balance=balance,
        is_contract=address_view.is_contract,
        note=note,
    )


async def _balance(provider: Provider, address: str) -> float | None:
    """The address's balance as a float, or ``None`` if it could not be read or is too large for
    one. Only reached when the provider advertises ``BALANCE``."""
    if not provider.supports(Capability.BALANCE):
        return None
    try:
        held = await provider.get_balance(address)
    except ChainlensError:
        return None
    return float(held.amount)
