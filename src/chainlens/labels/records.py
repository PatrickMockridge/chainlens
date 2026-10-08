"""The label record format, and why every record carries a citation.

A label is an assertion: *this address is that*. This library's whole position is that an
assertion without a stated ground is not a record, which is the rule the case study applies to a
claim (``falsifier``) and the annotation form applies to a person's evidence (``basis``). A label
is the third place the same rule applies, so **a record whose source is not a URL is refused**:
a reader who cannot go and read the assertion cannot weigh it, and a label nobody can check is
indistinguishable from a guess.

The format is a small YAML document with a header, one file per source:

.. code-block:: yaml

    provider: events
    source_kind: imported
    licence: this repository's own curation, one entry per cited source
    description: ...
    labels:
      - name: The DAO
        kind: dao
        addresses: ["0xbb9bc244d798123fde783fcc1c72d3bb8c189413"]
        source: https://eip.tools/eip/779
        note: named in the DAO Fork meta-EIP

The header is not boilerplate. ``licence`` is what makes the repository's data-licensing rule
checkable rather than a promise — a test asserts every committed file declares one — and
``provider`` is the name a label carries so that a reader, meeting two sources that disagree,
can see which said what.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date
from pathlib import Path

import yaml
from pydantic import Field, field_validator, model_validator

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel
from chainlens.models.entities import Label
from chainlens.models.enums import Chain, EntityKind, LabelSource

__all__ = [
    "DATA_DIR",
    "Corroboration",
    "LabelFile",
    "LabelRecord",
    "RecordError",
    "load_directory",
    "load_file",
]

#: Where the committed label data lives. Beside the code rather than in a top-level directory,
#: because it ships inside the wheel: a label set that only exists in a git checkout is a label
#: set that does not work when the library is installed.
DATA_DIR = Path(__file__).parent / "data"


class RecordError(ChainlensError):
    """A label file, or one record in it, is not usable."""


class Corroboration(LensModel):
    """What the chain was asked, and what it said back.

    **A citation is not evidence, and this is the field that admits it.** Everywhere else in this
    library a fact traces to bytes a provider returned; a label traced to a URL, which is a
    weaker grounding — a document can assert an address that does not exist, and a copied string
    can be one character wrong in a way no reader would catch. So each record also carries what
    the chain showed when somebody looked.

    It is recorded rather than merely asserted for two reasons. A reader can re-run it, and a
    value that drifts — a balance that moves because the coins moved — is visible as drift rather
    than silently stale. ``tests/labels/verify_corroboration.py`` re-runs every one of these and
    reports what changed; it is a ``make`` target rather than a test because the suite runs with
    the network blocked.

    Attributes:
        chain: which chain was queried. The provider layer is chain-scoped; labels are not.
        observed_at: the date it was checked. A number without a date is a claim about the past
            made in the present.
        received: total ever received, in the chain's native unit. Only UTXO chains can answer
            this without an indexer, which is why it is optional.
        balance: what the address holds now.
        is_contract: whether there is code at the address, which is checkable on an account chain
            and is how a named multisig or token contract can be told from an address that was
            merely typed into a document.
        note: what the numbers mean, since they are corroboration rather than proof: the chain can
            show that an address holds what a document says it holds, never that the document is
            right about whose it is.
    """

    chain: Chain
    observed_at: date
    received: float | None = None
    balance: float | None = None
    #: How many separate payments arrived. The crowdsale's strongest number is not its total but
    #: its *shape*: a 42-day sale is thousands of payments of ordinary size, and 31,726 BTC
    #: arriving in 9,084 of them is what a crowdsale looks like where a hoard looks like a
    #: handful of large transfers.
    funding_outputs: int | None = None
    is_contract: bool | None = None
    note: str | None = None


class LabelRecord(LensModel):
    """One source's assertion about one or more addresses, and what the chain says about it.

    Two grounds, and both are required. The citation says *who asserts this*; the corroboration
    says *what was checked*, which is a different thing and the one this library applies
    everywhere else.

    Attributes:
        name: what the source calls it — "The DAO", "Hydra Market". This is the *identity*;
            :attr:`kind` is only the category.
        kind: what kind of actor it is believed to be.
        addresses: every address the assertion covers. One record may name several — a contract
            and its withdrawal contract are one fact about one thing.
        source: a URL where the assertion can be read. Required, and required to be a URL.
        corroboration: what the chain showed when the address was looked up.
        note: what a reader needs in order not to over-rate this entry, such as "this rests on a
            public statement rather than a court filing". The strength of a source is not the
            same across entries and the file says so per entry rather than averaging it.
        confidence: how sure the *source* is, when it says. Absent means it did not.
    """

    name: str = Field(min_length=1)
    kind: EntityKind
    # No `min_length` here: it would fire before `_every_address_is_one` and answer an empty
    # address list with pydantic's "at least 1 item", which says what the shape is and not
    # why a label without an address is not a label.
    addresses: tuple[str, ...]
    source: str
    corroboration: Mapping[str, Corroboration]
    note: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _every_address_was_looked_up(self) -> LabelRecord:
        """Refuse a record that cites a document but checked nothing.

        This is the invariant that makes the corroboration a requirement rather than a
        courtesy: a label whose address was never queried is the thing this field exists to
        stop being normal. The reverse — a corroboration for an address the record does not
        claim — is also refused, because it is a leftover from before an address was removed.
        """
        claimed = set(self.addresses)
        looked_up = set(self.corroboration)
        if claimed - looked_up:
            raise ValueError(
                f"no corroboration for {sorted(claimed - looked_up)}; every address a record"
                " asserts has to say what the chain showed when it was checked"
            )
        if looked_up - claimed:
            raise ValueError(
                f"corroboration for {sorted(looked_up - claimed)}, which this record does not"
                " assert"
            )
        return self

    @field_validator("addresses")
    @classmethod
    def _every_address_is_one(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(address.strip() for address in value if address.strip())
        if not cleaned:
            raise ValueError(
                "a label with no address says nothing about anything; drop the record or give "
                "it the address it is about"
            )
        return cleaned

    @field_validator("source")
    @classmethod
    def _the_source_is_a_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError(
                f"a label's source must be a URL a reader can open, got {stripped!r}. An "
                "assertion nobody can check is indistinguishable from a guess, which is the "
                "one thing a label may not be"
            )
        return stripped

    def as_label(self, address: str, *, provider: str, source: LabelSource) -> Label:
        """This record as a :class:`Label`, for one of the addresses it covers."""
        return Label(
            name=self.name,
            source=source,
            kind=self.kind,
            confidence=self.confidence,
            address=address,
            url=self.source,
            provider=provider,
        )


class LabelFile(LensModel):
    """One committed file: where it came from, under what licence, and what it asserts.

    Attributes:
        provider: the name a label from this file carries, so a merger of several sources can
            still say which one asserted what.
        source_kind: whether these came from a provider or were imported from published
            sources. It decides what a reader is told about who is responsible.
        licence: what the data may be redistributed under. Required, and asserted by a test over
            every committed file, because "we checked the licence" is not a checkable statement.
        description: a sentence for somebody who has just found the file.
        labels: the assertions.
    """

    provider: str = Field(min_length=1)
    source_kind: LabelSource = LabelSource.IMPORTED
    licence: str = Field(min_length=1)
    description: str = Field(min_length=1)
    labels: tuple[LabelRecord, ...] = ()

    def by_address(self) -> Mapping[str, tuple[Label, ...]]:
        """Every label in the file, keyed by address.

        A record covering several addresses produces one label per address, each carrying the
        same citation — because "this contract and that contract are both The DAO" is two facts
        about two addresses, and a lookup that returned the pair for either is not wrong but is
        not what a caller asked for either.
        """
        found: dict[str, list[Label]] = {}
        for record in self.labels:
            for address in record.addresses:
                found.setdefault(address, []).append(
                    record.as_label(address, provider=self.provider, source=self.source_kind)
                )
        return {address: tuple(labels) for address, labels in found.items()}


def load_file(path: Path) -> LabelFile:
    """Read one label file.

    Raises:
        RecordError: the file is unreadable, is not YAML, or does not fit the shape. The message
            names the file and the offending key, because "invalid labels" sends a reader to look
            at a thousand entries.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RecordError(f"{path}: could not be read as YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecordError(
            f"{path}: expected a mapping with a `labels` key, got {type(raw).__name__}"
        )
    try:
        return LabelFile.model_validate(raw)
    except ValueError as exc:
        raise RecordError(f"{path}: {exc}") from exc


def load_directory(directory: Path | None = None) -> Iterator[LabelFile]:
    """Every ``*.yaml`` in a directory, in filename order.

    Order matters and is by filename rather than by anything the file says, so that a merge is
    deterministic: two sources carrying the same address must produce the same tuple every run,
    or a fixture comparing them would flake.
    """
    root = DATA_DIR if directory is None else directory
    for path in sorted(root.glob("*.yaml")):
        yield load_file(path)
