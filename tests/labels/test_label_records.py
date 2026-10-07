"""The label record format, and the one rule that makes it a record.

A label is an assertion — *this address is that* — and this library's position everywhere else is
that an assertion without a stated ground is not one. These tests are that rule, applied to labels:
the citation is required, it has to be a URL, and every committed file has to say what its data may
be redistributed under.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from chainlens.labels.records import DATA_DIR, LabelFile, RecordError, load_directory, load_file
from chainlens.models.enums import Chain, EntityKind, LabelSource
from chainlens.notes.addresses import AddressMention
from chainlens.providers.base import Provider

#: An address the ingest tests agree on, so the record-level tests can use the same one.
INGEST_ADDRESS = "0x" + "ab" * 20


def _file(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "provider": "test",
        "licence": "CC0-1.0",
        "description": "a test file",
        "labels": [
            {
                "name": "Example",
                "kind": "exchange",
                "addresses": ["1Example"],
                "source": "https://example.test/says-so",
                "corroboration": {
                    "1Example": {
                        "chain": "bitcoin",
                        "observed_at": "2026-10-07",
                        "balance": 1.0,
                    }
                },
            }
        ],
    }
    return {**fields, **overrides}


def _write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


class TestARecordNeedsAGround:
    def test_a_label_with_no_openable_source_is_refused(self) -> None:
        """The rule the whole format exists for.

        An entry whose source is "some forum post" cannot be checked, and a label nobody can check
        is indistinguishable from a guess — which is the one thing a label may not be.
        """
        for bad in ("", "   ", "a forum post", "eip-779"):
            with pytest.raises(ValueError, match="must be a URL"):
                LabelFile.model_validate(
                    _file(
                        labels=[
                            {
                                "name": "X",
                                "kind": "dao",
                                "addresses": ["a"],
                                "source": bad,
                                "corroboration": {
                                    "a": {"chain": "bitcoin", "observed_at": "2026-10-07"}
                                },
                            }
                        ]
                    )
                )

    def test_a_label_with_no_address_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no address"):
            LabelFile.model_validate(
                _file(
                    labels=[
                        {"name": "X", "kind": "dao", "addresses": [], "source": "https://x.test"}
                    ]
                )
            )
        with pytest.raises(ValueError, match="no address"):
            LabelFile.model_validate(
                _file(
                    labels=[
                        {
                            "name": "X",
                            "kind": "dao",
                            "addresses": ["  "],
                            "source": "https://x.test",
                        }
                    ]
                )
            )

    def test_a_record_that_checked_nothing_is_refused(self) -> None:
        """The field that makes this chain analysis rather than a literature review.

        A citation says who asserts an address. It does not say the address exists, and a string
        copied out of a document can be a character wrong in a way no reader would catch. The
        corroboration is the check that a copied string cannot survive, so a record without one is
        refused rather than quietly weaker than its neighbours.
        """
        payload = _file()
        del payload["labels"][0]["corroboration"]  # type: ignore[index]
        with pytest.raises(ValueError, match="corroboration"):
            LabelFile.model_validate(payload)

    def test_a_corroboration_for_an_address_the_record_does_not_assert_is_refused(self) -> None:
        """The leftover case: an address was removed and its lookup was not."""
        payload = _file()
        payload["labels"][0]["corroboration"]["elsewhere"] = {  # type: ignore[index]
            "chain": "bitcoin",
            "observed_at": "2026-10-07",
        }
        with pytest.raises(ValueError, match="does not"):
            LabelFile.model_validate(payload)

    def test_a_file_must_say_what_its_data_may_be_redistributed_under(self) -> None:
        """The repository's licensing rule, made checkable rather than promised.

        `docs/explanation/data-licensing.md` commits to shipping only data whose terms permit it.
        "We checked the licence" is not a statement a test can make; "every file declares one" is.
        """
        for missing in ("licence", "provider", "description"):
            payload = _file()
            del payload[missing]
            with pytest.raises(ValueError, match=missing):
                LabelFile.model_validate(payload)

    def test_the_source_kind_defaults_to_imported(self) -> None:
        """Not `provider`: these files are read rather than fetched from a service."""
        assert LabelFile.model_validate(_file()).source_kind is LabelSource.IMPORTED
        assert LabelFile.model_validate(_file()).source_kind is not LabelSource.PROVIDER


class TestReadingFiles:
    def test_a_file_loads_with_everything_it_declares(self, tmp_path: Path) -> None:
        loaded = load_file(_write(tmp_path, "one.yaml", _file()))
        assert loaded.provider == "test"
        assert loaded.licence == "CC0-1.0"
        assert len(loaded.labels) == 1
        assert loaded.labels[0].kind is EntityKind.EXCHANGE

    def test_a_file_that_is_not_a_mapping_is_named_as_such(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(RecordError, match="expected a mapping"):
            load_file(path)

    def test_an_unreadable_file_names_itself(self, tmp_path: Path) -> None:
        with pytest.raises(RecordError, match="could not be read"):
            load_file(tmp_path / "absent.yaml")

    def test_files_load_in_filename_order(self, tmp_path: Path) -> None:
        """Deterministic, so a merge of two sources is the same tuple every run.

        A fixture comparing label tuples would otherwise flake on directory order, which is exactly
        the kind of failure that gets a test deleted rather than fixed.
        """
        _write(tmp_path, "b-second.yaml", _file(provider="second"))
        _write(tmp_path, "a-first.yaml", _file(provider="first"))
        assert [f.provider for f in load_directory(tmp_path)] == ["first", "second"]


class TestTheCommittedData:
    def test_every_committed_file_declares_a_licence(self) -> None:
        files = list(load_directory(DATA_DIR))
        assert files, "the label data is missing; the provider would answer nothing"
        for label_file in files:
            assert label_file.licence.strip(), f"{label_file.provider} declares no licence"

    def test_every_committed_address_was_looked_up_on_chain(self) -> None:
        """Over the real data: every address here has been queried and the answer recorded."""
        checked = 0
        for label_file in load_directory(DATA_DIR):
            for record in label_file.labels:
                for address in record.addresses:
                    observation = record.corroboration[address]
                    assert observation.observed_at, f"{record.name}: no date on the lookup"
                    assert (
                        observation.received is not None
                        or observation.balance is not None
                        or observation.is_contract is not None
                    ), f"{record.name}/{address}: the lookup recorded nothing"
                    checked += 1
        assert checked >= 8, f"only {checked} addresses corroborated"

    def test_every_committed_entry_carries_an_openable_citation(self) -> None:
        """Checked over the real data, not a fixture: this is the promise the file makes."""
        for label_file in load_directory(DATA_DIR):
            for record in label_file.labels:
                assert record.source.startswith("https://"), (
                    f"{label_file.provider}/{record.name} cites {record.source!r}"
                )
                assert record.name.strip()

    def test_a_record_covering_several_addresses_yields_one_label_each(self) -> None:
        """The DAO's contract and its withdraw contract are two addresses and one fact."""
        dao = next(
            label
            for label_file in load_directory(DATA_DIR)
            for label in label_file.labels
            if label.name == "The DAO"
        )
        assert len(dao.addresses) >= 2
        labels = dao.as_label(dao.addresses[0], provider="events", source=LabelSource.IMPORTED)
        assert labels.address == dao.addresses[0]
        assert labels.name == "The DAO"
        assert labels.provider == "events"


class TestIngestingAScreenshotLabelColumn:
    """A vendor's table becomes a label file, or it does not become anything.

    What matters is that the format's invariants are *satisfied* rather than relaxed: a record
    with no citable source, or with an address nobody looked up, is exactly what those two fields
    exist to prevent, and an ingest that dodged them would be the one place in this library where
    a label arrives with nothing behind it.
    """

    def _mentions(self, *tokens: str) -> tuple[AddressMention, ...]:
        from chainlens.notes.addresses import MentionKind

        made = []
        for token in tokens:
            usable = token.startswith("0x") and len(token) == 42
            made.append(
                AddressMention(
                    as_written=token,
                    kind=MentionKind.USABLE if usable else MentionKind.TRUNCATED,
                    address=token if usable else None,
                    note="table.png",
                    transcribed=True,
                )
            )
        return tuple(made)

    def _provider(
        self, address: str, *, balance: int = 1_000, is_contract: bool = False
    ) -> Provider:
        from chainlens.models.enums import Chain
        from chainlens.models.primitives import Address, AssetRef, Balance
        from chainlens.providers.base import BaseProvider
        from chainlens.providers.capabilities import Capability, provides

        class P(BaseProvider):
            name = "fake-chain"
            chain = Chain.ETHEREUM

            def __init__(self) -> None:
                super().__init__(settings=None)

            @provides(Capability.ADDRESS)
            async def get_address(self, candidate: str) -> Address:
                return Address(chain=Chain.ETHEREUM, address=candidate, is_contract=is_contract)

            @provides(Capability.BALANCE)
            async def get_balance(self, candidate: str) -> Balance:
                return Balance(
                    chain=Chain.ETHEREUM,
                    address=candidate,
                    amount=balance,
                    asset=AssetRef.native(Chain.ETHEREUM, symbol="ETH", decimals=18),
                )

        return P()

    ADDRESS = INGEST_ADDRESS
    TRUNCATED = "0x5ed8cee6b63b1c6afce..."

    @pytest.mark.anyio
    async def test_a_usable_address_becomes_a_corroborated_record(self) -> None:
        from chainlens.labels.ingest import ingest_labels

        report = await ingest_labels(
            self._mentions(self.ADDRESS),
            provider=self._provider(self.ADDRESS, balance=2_500, is_contract=True),
            name="Some Vendor",
            source="https://example.invalid/table",
            kind=EntityKind.SERVICE,
            licence="private — not for redistribution",
        )

        assert report.kept == 1
        record = report.file.labels[0]  # type: ignore[union-attr]
        assert record.name == "Some Vendor"
        assert record.source == "https://example.invalid/table"
        assert record.addresses == (self.ADDRESS,)
        corroboration = record.corroboration[self.ADDRESS]
        assert corroboration.is_contract is True
        assert corroboration.balance == 2_500.0

    @pytest.mark.anyio
    async def test_a_truncated_address_becomes_nothing_and_is_reported(self) -> None:
        """It cannot be looked up, so it cannot be corroborated, so the format refuses it — and
        completing it or matching it by prefix would manufacture an assertion nobody made."""
        from chainlens.labels.ingest import ingest_labels

        report = await ingest_labels(
            self._mentions(self.ADDRESS, self.TRUNCATED),
            provider=self._provider(self.ADDRESS),
            name="Some Vendor",
            source="https://example.invalid/table",
            kind=EntityKind.SERVICE,
            licence="private — not for redistribution",
        )

        assert report.addresses == 1, "only the address that could be looked up"
        assert [token for token, _why in report.skipped] == [self.TRUNCATED]
        assert "truncated in the note" in report.skipped[0][1]

    @pytest.mark.anyio
    async def test_nothing_usable_means_no_file_rather_than_an_empty_one(self) -> None:
        from chainlens.labels.ingest import ingest_labels

        report = await ingest_labels(
            self._mentions(self.TRUNCATED),
            provider=self._provider(self.ADDRESS),
            name="Some Vendor",
            source="https://example.invalid/table",
            kind=EntityKind.SERVICE,
            licence="private — not for redistribution",
        )

        assert report.file is None
        assert report.kept == 0

    @pytest.mark.anyio
    async def test_an_address_the_chain_could_not_read_is_left_out_not_guessed_at(self) -> None:
        from chainlens.exceptions import NotFoundError
        from chainlens.labels.ingest import ingest_labels
        from chainlens.models.enums import Chain
        from chainlens.models.primitives import Address
        from chainlens.providers.base import BaseProvider
        from chainlens.providers.capabilities import Capability, provides

        class Missing(BaseProvider):
            name = "missing"
            chain = Chain.ETHEREUM

            def __init__(self) -> None:
                super().__init__(settings=None)

            @provides(Capability.ADDRESS)
            async def get_address(self, candidate: str) -> Address:
                raise NotFoundError("missing", candidate)

        report = await ingest_labels(
            self._mentions(self.ADDRESS),
            provider=Missing(),
            name="Some Vendor",
            source="https://example.invalid/table",
            kind=EntityKind.SERVICE,
            licence="private — not for redistribution",
        )

        assert report.file is None

    @pytest.mark.anyio
    async def test_a_provider_that_cannot_read_an_address_says_so_once(self) -> None:
        """The format would refuse every record anyway; forty identical validator failures is a
        worse way to say it."""
        from chainlens.exceptions import ChainlensError
        from chainlens.labels.ingest import ingest_labels
        from chainlens.models.enums import Chain
        from chainlens.providers.base import BaseProvider

        class Blind(BaseProvider):
            name = "blind"
            chain = Chain.ETHEREUM

            def __init__(self) -> None:
                super().__init__(settings=None)

        with pytest.raises(ChainlensError, match="cannot read an address"):
            await ingest_labels(
                self._mentions(self.ADDRESS),
                provider=Blind(),
                name="Some Vendor",
                source="https://example.invalid/table",
                kind=EntityKind.SERVICE,
                licence="private — not for redistribution",
            )

    def test_the_format_still_refuses_a_record_that_cites_nothing(self) -> None:
        """The invariants the ingest exists to satisfy, restated here so that relaxing one in the
        ingest would show up as this test failing.

        A label with no address says nothing about anything, and a source that is not a URL is an
        assertion nobody can check — which is a guess with a name.
        """
        from chainlens.labels.records import Corroboration, LabelRecord

        corroboration = {
            INGEST_ADDRESS: Corroboration(
                chain=Chain.ETHEREUM, observed_at=datetime.now(UTC).date()
            )
        }

        with pytest.raises(ValueError, match="no address says nothing"):
            LabelRecord(
                name="x",
                kind=EntityKind.SERVICE,
                addresses=(),
                source="https://example.invalid/t",
                corroboration={},
            )
        with pytest.raises(ValueError, match="URL"):
            LabelRecord(
                name="x",
                kind=EntityKind.SERVICE,
                addresses=(INGEST_ADDRESS,),
                source="not a url",
                corroboration=corroboration,
            )
