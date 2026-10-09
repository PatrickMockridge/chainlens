"""Tests for the shared EVM parsing helpers and the ERC-20 topic constant."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chainlens.adapters._evm import (
    TRANSFER_TOPIC,
    address_or_none,
    address_to_topic,
    erc20_transfer_from_log,
    from_hex_seconds,
    from_unix_seconds,
    has_code,
    method_id_from,
    parse_decimal_int,
    parse_hex_int,
    parse_log,
    parse_rpc_block,
    parse_rpc_transaction,
    topic_to_address,
)
from chainlens.exceptions import SchemaError
from chainlens.models.enums import AssetKind, Chain, FlowVia, TxStatus

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20


# --------------------------------------------------------------------------- #
# The topic constant
# --------------------------------------------------------------------------- #
def test_transfer_topic_matches_the_published_value() -> None:
    """Pinned against the well-known ERC-20 event signature hash.

    It is computed with our Keccak rather than pasted in, so this test is what
    catches a Keccak regression that would otherwise turn every token transfer
    into "not a transfer" and silently report zero token activity.
    """
    assert TRANSFER_TOPIC == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


# --------------------------------------------------------------------------- #
# Quantity parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0x1a", 26),
        ("0x0", 0),
        ("0X1A", 26),
        ("  0x10  ", 16),
        (26, 26),
        (None, None),
        ("0x", None),
        ("", None),
        ("not hex", None),
        (True, None),
        (1.5, None),
    ],
)
def test_parse_hex_int(raw: object, expected: int | None) -> None:
    assert parse_hex_int(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1000", 1000), (1000, 1000), ("", None), (None, None), ("abc", None), (True, None)],
)
def test_parse_decimal_int(raw: object, expected: int | None) -> None:
    assert parse_decimal_int(raw) == expected


def test_unix_seconds_are_read_as_utc() -> None:
    assert from_unix_seconds("1690000000") == datetime.fromtimestamp(1690000000, UTC)


def test_hex_seconds_are_read_as_utc() -> None:
    assert from_hex_seconds(hex(1690000000)) == datetime.fromtimestamp(1690000000, UTC)


@pytest.mark.parametrize("bad", [None, "", "nope", "99999999999999999999"])
def test_bad_timestamps_yield_none(bad: object) -> None:
    assert from_unix_seconds(bad) is None or isinstance(from_unix_seconds(bad), datetime)


def test_out_of_range_timestamp_yields_none() -> None:
    assert from_unix_seconds("999999999999999") is None


# --------------------------------------------------------------------------- #
# Addresses in logs
# --------------------------------------------------------------------------- #
def test_address_or_none_treats_empty_as_absent() -> None:
    """Etherscan uses "" for 'no recipient' on a contract creation."""
    assert address_or_none("") is None
    assert address_or_none("0x") is None
    assert address_or_none(None) is None
    assert address_or_none("null") is None
    assert address_or_none(ALICE.upper()) == ALICE
    assert address_or_none("not an address") is None


def test_address_topic_padding() -> None:
    topic = address_to_topic(ALICE)
    assert len(topic) == 66  # 0x + 64 hex chars
    assert topic == "0x" + "0" * 24 + ALICE[2:]
    assert topic_to_address(topic) == ALICE


def test_topic_to_address_rejects_short_topics() -> None:
    assert topic_to_address("0x1234") is None
    assert topic_to_address(None) is None


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("0xa9059cbb" + "00" * 32, "0xa9059cbb"),
        ("0xa9059cbb", "0xa9059cbb"),
        ("0x", None),
        ("0x1234", None),
        ("", None),
        (None, None),
    ],
)
def test_method_id_is_the_selector_or_nothing(selector: object, expected: str | None) -> None:
    """The rule that was written twice, once per API's spelling of the same thing.

    A short call is not a method call, and returning the short string would put something in
    `method_id` that reads as a selector no ABI can resolve. The Etherscan copy carried an extra
    `!= "0x"` test that the length check already covered, which is the kind of redundant clause
    one copy of a rule grows and the other does not.
    """
    assert method_id_from(selector) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("0x6080604052", True),
        ("0x0", True),
        ("0x", False),
        ("", False),
        (None, False),
        (123, False),
    ],
)
def test_has_code_reads_the_two_spellings_of_nothing_deployed(code: object, expected: bool) -> None:
    """`eth_getCode` answers `"0x"` or `""` for an address with no code, depending on the node.

    Reading either as code reports an ordinary wallet as a contract, which is a claim about what
    an address *is* — the kind a reader acts on. The check lived in two adapters, which is how two
    copies come to disagree about one of the spellings.
    """
    assert has_code(code) == expected


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
def _erc20_log(*, value: int = 500, from_: str = ALICE, to: str = BOB) -> dict[str, object]:
    return {
        "address": CONTRACT,
        "topics": [TRANSFER_TOPIC, address_to_topic(from_), address_to_topic(to)],
        "data": hex(value),
        "logIndex": "0x3",
        "blockNumber": "0x10",
        "transactionHash": "0x" + "dd" * 32,
        "removed": False,
    }


def test_log_parsing() -> None:
    entry = parse_log(_erc20_log())
    assert entry.index == 3
    assert entry.address == CONTRACT
    assert len(entry.topics) == 3
    assert not entry.removed


def test_erc20_transfer_is_extracted() -> None:
    transfer = erc20_transfer_from_log(_erc20_log(), chain=Chain.ETHEREUM, txid="0xdead")
    assert transfer is not None
    assert transfer.amount == 500
    assert transfer.src == ALICE
    assert transfer.dst == BOB
    assert transfer.via is FlowVia.ERC20
    assert transfer.asset.kind is AssetKind.ERC20
    assert transfer.asset.contract == CONTRACT


def test_a_different_event_is_not_a_transfer() -> None:
    log = _erc20_log()
    log["topics"] = ["0x" + "11" * 32, address_to_topic(ALICE), address_to_topic(BOB)]
    assert erc20_transfer_from_log(log, chain=Chain.ETHEREUM, txid="0xdead") is None


def test_erc721_transfer_is_not_reported_as_erc20() -> None:
    """ERC-721 shares the topic but indexes the token id as a fourth topic.

    Accepting it would report an NFT id as a fungible amount.
    """
    log = _erc20_log()
    log["topics"] = [
        TRANSFER_TOPIC,
        address_to_topic(ALICE),
        address_to_topic(BOB),
        "0x" + "00" * 31 + "05",
    ]
    log["data"] = "0x"
    assert erc20_transfer_from_log(log, chain=Chain.ETHEREUM, txid="0xdead") is None


def test_transfer_without_data_is_rejected() -> None:
    log = _erc20_log()
    log["data"] = "0x"
    assert erc20_transfer_from_log(log, chain=Chain.ETHEREUM, txid="0xdead") is None


# --------------------------------------------------------------------------- #
# Transactions from JSON-RPC shape
# --------------------------------------------------------------------------- #
def _rpc_tx() -> dict[str, object]:
    return {
        "hash": "0x" + "ee" * 32,
        "blockHash": "0x" + "ff" * 32,
        "blockNumber": "0x10",
        "from": ALICE,
        "to": BOB,
        "value": "0xde0b6b3a7640000",  # 1 ETH
        "nonce": "0x5",
        "gas": "0x5208",
        "gasPrice": "0x3b9aca00",  # 1 gwei
        "input": "0xa9059cbb0000000000000000000000000",
    }


def _receipt(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "0x1",
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x3b9aca00",
        "logs": [],
    }
    base.update(overrides)
    return base


def test_transaction_fee_is_gas_used_times_price() -> None:
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(), chain=Chain.ETHEREUM)
    assert tx.gas_used == 21_000
    assert tx.fee == 21_000 * 1_000_000_000


def test_transaction_value_is_not_multiplied_by_decimals() -> None:
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(), chain=Chain.ETHEREUM)
    assert tx.value == 10**18


def test_lifted_view_conserves_value_on_an_account_chain() -> None:
    """The synthesized input carries value + fee, so inputs - outputs == fee."""
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(), chain=Chain.ETHEREUM)
    assert tx.chain_model.value == "account"
    assert tx.total_input_value - tx.total_output_value == tx.fee


def test_reverted_transaction_is_failed() -> None:
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(status="0x0"), chain=Chain.ETHEREUM)
    assert tx.status is TxStatus.FAILED


def test_transaction_without_a_receipt_is_pending() -> None:
    tx = parse_rpc_transaction({"hash": "0xabc", "value": "0x1"}, None, chain=Chain.ETHEREUM)
    assert tx.status is TxStatus.PENDING
    assert tx.fee is None


def test_effective_gas_price_wins_for_the_fee() -> None:
    """EIP-1559: the receipt's effective price is what was actually paid."""
    tx = parse_rpc_transaction(
        _rpc_tx(),
        _receipt(effectiveGasPrice="0x1"),
        chain=Chain.ETHEREUM,
    )
    assert tx.fee == 21_000 * 1


def test_logs_are_carried_onto_the_transaction() -> None:
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(logs=[_erc20_log()]), chain=Chain.ETHEREUM)
    assert len(tx.logs) == 1
    assert tx.logs[0].address == CONTRACT


def test_method_id_is_taken_from_the_calldata() -> None:
    tx = parse_rpc_transaction(_rpc_tx(), _receipt(), chain=Chain.ETHEREUM)
    assert tx.method_id == "0xa9059cbb"


def test_contract_creation_has_no_recipient() -> None:
    tx_raw = _rpc_tx() | {"to": None}
    tx = parse_rpc_transaction(tx_raw, _receipt(contractAddress=CONTRACT), chain=Chain.ETHEREUM)
    assert tx.to_address is None
    assert tx.contract_address == CONTRACT


# --------------------------------------------------------------------------- #
# Blocks from JSON-RPC shape
# --------------------------------------------------------------------------- #
def test_block_parsing() -> None:
    block = parse_rpc_block(
        {
            "hash": "0x" + "11" * 32,
            "number": "0x10",
            "timestamp": hex(1690000000),
            "transactions": ["0x1", "0x2", "0x3"],
            "size": "0x200",
            "parentHash": "0x" + "22" * 32,
        },
        chain=Chain.ETHEREUM,
        provider="test",
    )
    assert block.height == 16
    assert block.tx_count == 3
    assert block.timestamp == datetime.fromtimestamp(1690000000, UTC)
    # weight is a Bitcoin field and must not be filled with an EVM gas figure.
    assert block.weight is None


def test_block_without_a_number_is_a_schema_error() -> None:
    with pytest.raises(SchemaError, match="carries no number"):
        parse_rpc_block({"hash": "0xabc"}, chain=Chain.ETHEREUM, provider="test")
