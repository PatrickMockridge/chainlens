"""The Ethereum crowdsale preset, and the row rule it turns on.

The rule is fitted to one table and the tests say so: a row of that table is paid from a bitcoin
address, and its issued column is either an ethereum address or the word ``unknown``. Every
condition here was put in after a *measured* false positive, and the tests name the measurement —
a mining table's block heights read exactly like amounts, and a sentence of prose can hold two
bitcoin addresses and a number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chainlens.models.enums import Chain
from chainlens.notes.corpus import Corpus, Note, NoteKind
from chainlens.presets.crowdsale import (
    allocation_from,
    check_allocation,
    check_rate,
    rows_in,
    summarise,
)
from chainlens.presets.records import CheckStatus, Preset, PresetError, load_file

#: The addresses the sample rows are built from, so no line of this file is a long literal.
PAID = "1FV85vVMaw9KmjqgRq2gd1R3n9Prb8e2tv"
UNCLAIMED = "1296o5WQV2RfAfahBArF8wzRFRZMsbi2f4"
ISSUED = "0x9d2bfc36106f038250c01801685785b16c86c60d"
MINER = "0xea674fdde714fd979de3edf0f56aa9716b898ec8"
SEIZED = "18yWFVddqNrGE966zwXTpyJgYJgr82SvMs"


def _sale_row(paid: str, issued: str, *, paid_amount: str, issued_amount: str) -> str:
    return f"{paid} {issued} GB 12_8 Lubin 190 {paid_amount} {issued_amount}"


#: Four shapes the real corpus holds, and only the first two are rows of the sale.
TABLE = "\n".join(
    [
        "BTC Address ETH Address Label BTC Paid ETH Received",
        _sale_row(PAID, ISSUED, paid_amount="190", issued_amount="380,000"),
        f"{UNCLAIMED} unknown GB 8 Lubin 1296 10 10 20,000",
        f"1 {MINER} Ethermine 22.80% 3.44 1191938 15537592 N",
        f"Approximately 1,605 Bitcoins seized from someone and moved to {SEIZED}",
    ]
)

ICO = "ethereum-ico"


def _corpus(body: str) -> Corpus:
    return Corpus(
        root="notes",
        notes=(Note(path="table.txt", kind=NoteKind.TEXT, text=body, characters=len(body)),),
    )


def _preset() -> Preset:
    from chainlens.presets.records import DATA_DIR

    return load_file(DATA_DIR / f"{ICO}.yaml")


class TestThePresetItself:
    def test_it_ships_and_carries_a_citable_source(self) -> None:
        """A rule nobody can read is indistinguishable from an invention, which is why the field is
        required and why the loader refuses a preset without a URL."""
        preset = _preset()
        assert preset.name == ICO
        assert preset.source.startswith("https://")
        assert {tier.rate for tier in preset.rates} >= {2000.0, 1337.0}

    def test_a_preset_without_a_url_is_refused_by_name(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("name: x\nchain: ethereum\nsource: 'see the forum'\n", encoding="utf-8")
        with pytest.raises(PresetError, match="must be an http"):
            load_file(path)

    @pytest.mark.parametrize(
        ("implied", "expected"),
        [(2000.0, 2000.0), (1999.999, 2000.0), (2019.45, 2000.0), (1670.0, None), (1894.86, None)],
    )
    def test_a_rate_matches_a_tier_or_does_not(
        self, implied: float, expected: float | None
    ) -> None:
        """The tolerance exists for the rows a model transcribed to five decimal places:
        `157.40392` against `314,808` implies 1999.999…, which is the 2,000 tier and not a near
        miss. It is small because a wide window would pass a rate that is merely close, and the
        rows that match no tier are the interesting ones."""
        tier = _preset().rate_for(implied)
        assert (tier.rate if tier else None) == expected


class TestWhichLinesAreRows:
    def test_a_row_of_the_table_is_recognised(self) -> None:
        rows = rows_in(_corpus(TABLE), _preset())
        assert [(r.paid_text, r.issued_text) for r in rows] == [
            ("190", "380,000"),
            ("10", "20,000"),
        ]

    def test_a_mining_table_is_not(self) -> None:
        """Measured: without the paid-side condition the recognised set went from 8 rows to 31, and
        the extra 23 were block heights from a mining table whose rows carry an ethereum address and
        a column of numbers that read exactly like amounts."""
        rows = rows_in(_corpus(TABLE), _preset())
        assert all("Ethermine" not in row.text for row in rows)

    def test_a_row_whose_issued_column_says_unknown_is_still_a_row(self) -> None:
        """`unknown` is this table's word for a participant who never claimed an allocation. It is a
        fact worth keeping, and those rows still have a rate worth checking."""
        rows = rows_in(_corpus(TABLE), _preset())
        assert any(row.issued_address is None and row.paid_address for row in rows)

    def test_prose_holding_two_bitcoin_addresses_is_not_a_row(self) -> None:
        """It has the paid side and two numbers; what it does not have is the issued column."""
        rows = rows_in(_corpus(TABLE), _preset())
        assert all("seized" not in row.text for row in rows)

    def test_a_garbled_paid_address_excludes_the_row_and_that_is_the_stated_cost(self) -> None:
        """A row whose bitcoin address the transcription mangled is not recognised, even when its
        ethereum address is intact — and mangling is common in this corpus, because a base58
        address carries a checksum a dropped character fails, while an all-lowercase EVM one carries
        none and cannot be checked at all. The addresses are still found by `--addresses`; they are
        just not rows."""
        intact = _sale_row(PAID, ISSUED, paid_amount="190", issued_amount="380,000")
        # One character dropped from the base58 address, so the checksum no longer verifies.
        garbled = _sale_row(PAID[:-1], ISSUED, paid_amount="190", issued_amount="380,000")
        rows = rows_in(_corpus(f"{intact}\n{garbled}\n"), _preset())

        assert len(rows) == 1, "the garbled row was not built"
        assert rows[0].paid_address == PAID


class TestTheRateCheck:
    def test_a_row_at_the_opening_rate_matches_and_says_which_tier(self) -> None:
        row = rows_in(_corpus(TABLE), _preset())[0]
        outcome = check_rate(row, _preset())
        assert outcome.status is CheckStatus.MATCHED
        assert "2,000.00" in outcome.detail
        assert "opening" in outcome.detail, (
            "a reader needs to know which tier, not just that it fit"
        )

    def test_a_row_at_no_published_rate_is_flagged_and_says_why_it_matters(self) -> None:
        """`UNMATCHED` and not `REFUTED`: the likeliest cause is a misread column, and a status
        claiming refutation would not have earned it."""
        body = _sale_row(PAID, ISSUED, paid_amount="53", issued_amount="88,510")
        outcome = check_rate(rows_in(_corpus(body + "\n"), _preset())[0], _preset())
        assert outcome.status is CheckStatus.UNMATCHED
        assert "worth reading the image" in outcome.detail.lower()

    def test_a_totals_row_is_not_a_failure(self) -> None:
        """A total's rate blends every tier, so it matches none — and reporting that as a finding
        would flag the sale's own summary line as wrong."""
        preset = _preset()
        funding = preset.funding_address
        assert funding is not None
        body = _sale_row(funding, ISSUED, paid_amount="31,725", issued_amount="60,114,460")
        row = rows_in(_corpus(body + "\n"), preset)[0]
        assert row.is_summary, "the totals row pays into the address the sale collected into"
        outcome = check_rate(row, preset)
        assert outcome.status is CheckStatus.NOT_ASKABLE
        assert "blends every tier" in outcome.detail


class TestTheAllocationCheck:
    def test_with_no_record_supplied_it_says_so_rather_than_agreeing(self) -> None:
        """`not_checked` and `matched` are the two things a reader most needs to tell apart, and a
        check that defaulted to agreement would make the whole report worthless."""
        row = rows_in(_corpus(TABLE), _preset())[0]
        outcome = check_allocation(row)
        assert outcome.status is CheckStatus.NOT_CHECKED
        assert "not checked" in outcome.detail.lower()

    def test_it_agrees_when_the_record_holds_what_the_row_claims(self) -> None:
        row = rows_in(_corpus(TABLE), _preset())[0]
        address = row.issued_address
        assert address is not None
        allocation = {address.lower(): 380_000 * 10**18}
        outcome = check_allocation(row, allocation=allocation)
        assert outcome.status is CheckStatus.MATCHED
        assert "380,000" in outcome.detail

    def test_it_disagrees_and_gives_the_difference(self) -> None:
        row = rows_in(_corpus(TABLE), _preset())[0]
        address = row.issued_address
        assert address is not None
        outcome = check_allocation(row, allocation={address.lower(): 379_000 * 10**18})
        assert outcome.status is CheckStatus.UNMATCHED
        assert "-1,000" in outcome.detail or "1,000" in outcome.detail

    def test_an_address_the_record_does_not_hold_is_a_question(self) -> None:
        """Either the address was misread or it was not a participant, and this check cannot say
        which."""
        row = rows_in(_corpus(TABLE), _preset())[0]
        outcome = check_allocation(row, allocation={"0x" + "00" * 20: 1})
        assert outcome.status is CheckStatus.UNMATCHED
        assert "no allocation" in outcome.detail

    def test_a_row_with_no_issued_address_cannot_be_asked(self) -> None:
        body = f"{UNCLAIMED} unknown GB 8 Lubin 1296 10 10 20,000\n"
        row = rows_in(_corpus(body), _preset())[0]
        assert check_allocation(row).status is CheckStatus.NOT_ASKABLE


class TestTheAllocationFile:
    def _file(self, tmp_path: Path, payload: object) -> Path:
        path = tmp_path / "alloc.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_it_reads_the_shape_the_clients_publish(self, tmp_path: Path) -> None:
        path = self._file(
            tmp_path,
            {
                "accounts": {
                    "0xAbC0000000000000000000000000000000000001": {"balance": "0x1"},
                    # A builtin contract, which is not an allocation.
                    "0x0000000000000000000000000000000000000001": {
                        "builtin": {"name": "ecrecover"}
                    },
                }
            },
        )
        allocation = allocation_from(path)
        assert allocation == {"0xabc0000000000000000000000000000000000001": 1}, (
            "keyed lowercase, because the row's address is and the file's is checksummed"
        )

    def test_a_file_that_holds_no_allocation_is_loud(self, tmp_path: Path) -> None:
        """An empty mapping is indistinguishable from a working check that found nothing."""
        with pytest.raises(ValueError, match="no allocation"):
            allocation_from(self._file(tmp_path, {"accounts": {}}))

    def test_a_bare_amount_without_a_balance_wrapper_is_read(self, tmp_path: Path) -> None:
        allocation = allocation_from(
            self._file(tmp_path, {"alloc": {"0xAbC0000000000000000000000000000000000002": 5}})
        )
        assert allocation == {"0xabc0000000000000000000000000000000000002": 5}


class TestTheSummaryLine:
    def test_it_counts_every_status(self) -> None:
        rows = rows_in(_corpus(TABLE), _preset())
        outcomes = [[check_rate(row, _preset()), check_allocation(row)] for row in rows]
        line = summarise(rows, outcomes)
        assert "2 row(s)" in line
        assert "matched" in line
        assert "not_checked" in line


class TestOverTheRealCorpusShape:
    def test_the_two_chains_are_told_apart(self) -> None:
        """The paid side is bitcoin and the issued side is ethereum, and a row that swapped them
        would be a different table."""
        row = rows_in(_corpus(TABLE), _preset())[0]
        assert row.paid_address is not None
        assert not row.paid_address.startswith("0x")
        assert row.issued_address is not None
        assert row.issued_address.startswith("0x")
        assert _preset().chain is Chain.ETHEREUM
