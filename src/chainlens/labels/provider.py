"""A label provider that answers from committed files.

The first thing in this tree to implement
:data:`~chainlens.providers.capabilities.Capability.LABELS`.
Until it existed, ``check_label`` always took its "no label source is configured" branch, so an
attribution claim could only ever come back unresolved.

**Why a file rather than an API.** Every live labelling service forbids redistributing the labels
themselves — Etherscan's terms prohibit mirroring its datasets and licence the free tier to
personal and research use, Nansen marks its label endpoint prohibited, and the free sanctions APIs
permit a runtime answer while revoking cached copies on request. So a provider that fetched labels
from one of them could not ship the labels, could not be tested from a committed fixture, and would
make the library's output undependable the moment a key expired. What is redistributable is data,
and data is a file.

**Where the chain goes.** Labels are not chain-scoped: :class:`~chainlens.models.entities.Label`
has an address and no chain, and the overlay keys one by the *finding's* chain. The provider
protocol nonetheless requires a chain, and a composite refuses to mix them, so this takes the chain
it is composed under and answers from its data regardless. The data knows which addresses it holds;
the chain is what the registry sorts it by.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from chainlens.config import Settings
from chainlens.labels.records import LabelFile, load_directory
from chainlens.models.entities import Label
from chainlens.models.enums import Chain
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides

__all__ = ["LocalLabelProvider"]


class LocalLabelProvider(BaseProvider):
    """Labels read from ``labels/data/*.yaml``, or from a directory a caller names.

    Args:
        chain: the chain this instance is registered under. It does not restrict what the
            provider answers — see the module docstring — it decides what a composite will
            accept it alongside.
        directory: a directory of label files. Defaults to the committed data, which is what
            makes an installed ``chainlens`` know about Mt Gox without any setup.
        name: what to call this instance. The class attribute is ``"local-labels"``, which is
            right for the shipped data and wrong for a private set: ``check_label`` records which
            source asserted a label so a reader can weigh it, and a vendor's assertions attributed
            to "local-labels" would read as this library's own curation.
        settings: process settings, for the shape the base class expects. Nothing here reads
            the network, so nothing here reads a credential.
    """

    name = "local-labels"
    chain: Chain = Chain.BITCOIN

    #: Our own curation and a public-domain government list. Both may be redistributed, which is
    #: the only reason they are committed at all.
    redistributable = True

    def __init__(
        self,
        *,
        chain: Chain | None = None,
        directory: Path | None = None,
        name: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(settings=settings)
        if chain is not None:
            self.chain = chain
        if name is not None:
            self.name = name
        self._files: tuple[LabelFile, ...] = tuple(load_directory(directory))
        self._by_address: Mapping[str, tuple[Label, ...]] = self._merge()

    @property
    def files(self) -> tuple[LabelFile, ...]:
        """The files this provider answers from, so a caller can report its own coverage."""
        return self._files

    @property
    def address_count(self) -> int:
        """How many addresses it can answer about."""
        return len(self._by_address)

    def _merge(self) -> Mapping[str, tuple[Label, ...]]:
        """Every file's labels, concatenated by address and deduplicated.

        Two files disagreeing about one address is a *result*, not a conflict to resolve: an
        address that a sanctions list designates and a curated file calls an exchange yields both
        labels, each carrying the name of whoever asserted it. Silently preferring one would make
        the provider an adjudicator, which is not a job it has the standing for.
        """
        merged: dict[str, list[Label]] = {}
        seen: set[tuple[str, str, str, str | None]] = set()
        for label_file in self._files:
            for address, labels in label_file.by_address().items():
                for label in labels:
                    key = (address, label.name, label.kind.value, label.provider)
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.setdefault(address, []).append(label)
        return {address: tuple(labels) for address, labels in merged.items()}

    @provides(Capability.LABELS)
    async def get_labels(self, addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]:
        """What every committed source says about each address.

        An address nobody has labelled gets an empty tuple rather than being left out. The
        distinction is the checker's: ``check_label`` reads a *missing* key as a source that was
        never asked, and an empty tuple as a source that was asked and holds nothing — which are
        different findings with different remedies.
        """
        return {address: self._by_address.get(address, ()) for address in addresses}
