"""Shared EVM parsing helpers.

Private to the adapter package. Etherscan and JSON-RPC return the same concepts
under different spellings -- a hex-quantity ``0x1a`` in one, a decimal string
``"26"`` in the other -- so the conversion lives here rather than being duplicated
(and drifting) in both adapters.

The one piece of real domain knowledge is :data:`TRANSFER_TOPIC`, the hash of
``Transfer(address,address,uint256)`` that identifies an ERC-20 transfer log. It is
computed with our own Keccak rather than pasted in as a literal, so it cannot be a
typo, and ``tests/adapters/test_evm.py`` pins it against the published value.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from chainlens.codec import keccak256
from chainlens.codec.eth_address import normalize_address
from chainlens.exceptions import SchemaError
from chainlens.models.base import Provenance
from chainlens.models.enums import AssetKind, Chain, FlowVia, TxStatus
from chainlens.models.primitives import AssetRef, Block, LogEntry, Transaction, Transfer

__all__ = [
    "TRANSFER_TOPIC",
    "WEI_DECIMALS",
    "address_or_none",
    "address_to_topic",
    "erc20_transfer_from_log",
    "from_hex_seconds",
    "from_unix_seconds",
    "parse_decimal_int",
    "parse_hex_int",
    "parse_log",
    "parse_rpc_block",
    "parse_rpc_transaction",
    "topic_to_address",
]

#: ``keccak256("Transfer(address,address,uint256)")``.
TRANSFER_TOPIC = "0x" + keccak256(b"Transfer(address,address,uint256)").hex()

WEI_DECIMALS = 18

_ADDRESS_TOPIC_BYTES = 40


def parse_hex_int(value: Any) -> int | None:
    """Parse a JSON-RPC hex quantity (``"0x1a"``) into an int.

    Returns ``None`` for anything absent or unparseable, including the ``"0x"``
    that some nodes return for a zero-length field.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text in {"0x", "0X"}:
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def parse_decimal_int(value: Any) -> int | None:
    """Parse a decimal string or int, as Etherscan's flattened API returns."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def from_unix_seconds(value: Any) -> datetime | None:
    """Parse Etherscan's unix-seconds timestamps."""
    seconds = parse_decimal_int(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def from_hex_seconds(value: Any) -> datetime | None:
    """Parse JSON-RPC's hex-seconds timestamps."""
    seconds = parse_hex_int(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def address_or_none(value: Any) -> str | None:
    """Normalise an address to canonical lowercase, or ``None``.

    Etherscan uses the empty string for "no address" (contract creation has no
    recipient, and a successful call has no created contract), so ``""`` must
    become ``None`` rather than a ValueError.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"0x", "null"}:
        return None
    try:
        return normalize_address(text)
    except ValueError:
        return None


def topic_to_address(topic: Any) -> str | None:
    """Extract an address from a 32-byte log topic."""
    if not isinstance(topic, str):
        return None
    body = topic.strip().removeprefix("0x")
    if len(body) < _ADDRESS_TOPIC_BYTES:
        return None
    return address_or_none("0x" + body[-_ADDRESS_TOPIC_BYTES:])


def address_to_topic(address: str) -> str:
    """Pad an address to a 32-byte log topic, as ``eth_getLogs`` expects."""
    normalized = normalize_address(address)
    return "0x" + normalized[2:].rjust(64, "0")


def parse_log(raw: Mapping[str, Any]) -> LogEntry:
    """Parse a JSON-RPC log object."""
    return LogEntry(
        index=parse_hex_int(raw.get("logIndex")) or 0,
        address=address_or_none(raw.get("address")),
        topics=tuple(str(t) for t in (raw.get("topics") or [])),
        data=raw.get("data"),
        removed=bool(raw.get("removed", False)),
        raw=dict(raw),
    )


def erc20_transfer_from_log(
    raw: Mapping[str, Any],
    *,
    chain: Chain,
    txid: str,
    block_height: int | None = None,
    timestamp: datetime | None = None,
    provenance: Provenance | None = None,
) -> Transfer | None:
    """Extract an ERC-20 transfer from a log, or ``None`` if it is not one.

    An ERC-721 ``Transfer`` shares the same topic but indexes the token id as a
    fourth topic and carries no ``data``, so it is rejected here rather than being
    silently reported as a fungible amount.
    """
    topics = raw.get("topics") or []
    if not topics or not isinstance(topics[0], str):
        return None
    if topics[0].lower() != TRANSFER_TOPIC:
        return None
    if len(topics) != 3:
        return None
    amount = parse_hex_int(raw.get("data"))
    if amount is None:
        return None
    contract = address_or_none(raw.get("address"))
    return Transfer(
        chain=chain,
        asset=AssetRef(chain=chain, kind=AssetKind.ERC20, contract=contract),
        amount=amount,
        txid=txid,
        src=topic_to_address(topics[1]),
        dst=topic_to_address(topics[2]),
        index=parse_hex_int(raw.get("logIndex")),
        block_height=block_height,
        timestamp=timestamp,
        via=FlowVia.ERC20,
        provenance=provenance,
    )


def _status_from_receipt(receipt: Mapping[str, Any] | None) -> TxStatus:
    if receipt is None:
        return TxStatus.PENDING
    status = receipt.get("status")
    if status == "0x0":
        return TxStatus.FAILED
    if status == "0x1":
        return TxStatus.CONFIRMED
    return TxStatus.PENDING


def parse_rpc_transaction(
    tx: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    chain: Chain,
    provenance: Provenance | None = None,
) -> Transaction:
    """Build a :class:`Transaction` from a JSON-RPC transaction and its receipt.

    The receipt is optional because a pending transaction has none, but it is
    where ``gasUsed``, ``effectiveGasPrice``, ``status`` and the logs live. The fee
    is computed as ``gasUsed * effectiveGasPrice`` (falling back to ``gasPrice``),
    which is what makes the pseudo-UTXO view conserve value on an account chain.
    """
    gas_used = parse_hex_int(receipt.get("gasUsed")) if receipt else None
    effective = parse_hex_int(receipt.get("effectiveGasPrice")) if receipt else None
    gas_price = parse_hex_int(tx.get("gasPrice"))
    price_for_fee = effective if effective is not None else gas_price
    fee = gas_used * price_for_fee if gas_used is not None and price_for_fee is not None else None
    logs = tuple(parse_log(raw) for raw in ((receipt or {}).get("logs") or []))
    input_hex = str(tx.get("input") or "")

    return Transaction(
        chain=chain,
        txid=str(tx.get("hash", "")),
        status=_status_from_receipt(receipt),
        block_hash=tx.get("blockHash"),
        block_height=parse_hex_int(tx.get("blockNumber")),
        from_address=address_or_none(tx.get("from")),
        to_address=address_or_none(tx.get("to")),
        value=parse_hex_int(tx.get("value")),
        nonce=parse_hex_int(tx.get("nonce")),
        gas_limit=parse_hex_int(tx.get("gas")),
        gas_used=gas_used,
        gas_price=gas_price,
        effective_gas_price=effective,
        max_fee_per_gas=parse_hex_int(tx.get("maxFeePerGas")),
        max_priority_fee_per_gas=parse_hex_int(tx.get("maxPriorityFeePerGas")),
        contract_address=address_or_none((receipt or {}).get("contractAddress")),
        method_id=input_hex[:10] if len(input_hex) >= 10 else None,
        logs=logs,
        fee=fee,
        fee_asset=AssetRef.native(chain, symbol="ETH", decimals=WEI_DECIMALS),
        provenance=provenance,
    )


def parse_rpc_block(
    raw: Mapping[str, Any],
    *,
    chain: Chain,
    provider: str,
    provenance: Provenance | None = None,
) -> Block:
    """Build a :class:`Block` from a JSON-RPC block object.

    Raises:
        SchemaError: if the block carries no number. A block that cannot be placed
            on the chain is not something to guess about.
    """
    block_hash = str(raw.get("hash") or "")
    height = parse_hex_int(raw.get("number"))
    if height is None:
        raise SchemaError(provider, f"block {block_hash} payload carries no number")
    transactions = raw.get("transactions") or []
    return Block(
        chain=chain,
        hash=block_hash,
        height=height,
        timestamp=from_hex_seconds(raw.get("timestamp")),
        tx_count=len(transactions) if isinstance(transactions, list) else None,
        size=parse_hex_int(raw.get("size")),
        # ``weight`` is deliberately left unset: it is a Bitcoin block-weight field
        # and an EVM block's gasUsed means something else entirely. Filing one under
        # the other's name would be worse than omitting it.
        prev_hash=raw.get("parentHash"),
        provenance=provenance,
    )
