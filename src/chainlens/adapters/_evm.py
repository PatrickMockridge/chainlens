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
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from chainlens.adapters._payload import ProviderPayload, read_payload
from chainlens.codec import keccak256
from chainlens.codec.eth_address import normalize_address
from chainlens.exceptions import SchemaError
from chainlens.models.base import Provenance
from chainlens.models.enums import AssetKind, Chain, FlowVia, TxStatus
from chainlens.models.primitives import AssetRef, Block, LogEntry, Transaction, Transfer

__all__ = [
    "TRANSFER_TOPIC",
    "address_or_none",
    "address_to_topic",
    "erc20_transfer_from_log",
    "from_hex_seconds",
    "from_unix_seconds",
    "has_code",
    "method_id_from",
    "parse_decimal_int",
    "parse_hex_int",
    "parse_log",
    "parse_rpc_block",
    "parse_rpc_transaction",
    "topic_to_address",
]

#: ``keccak256("Transfer(address,address,uint256)")``.
TRANSFER_TOPIC = "0x" + keccak256(b"Transfer(address,address,uint256)").hex()

#: A log topic is one 32-byte ABI word, which is 64 hex characters.
_TOPIC_HEX_DIGITS = 64

#: An address fills the low 20 bytes of that word — 12 bytes of left-padding, then the address —
#: so it is the topic's last 40 hex characters. Named rather than written as `40` beside a bare
#: `64`, because the two are one layout and a reader who meets them apart has to work out that
#: one is the other's suffix.
_ADDRESS_HEX_DIGITS = 40

#: JSON-RPC spells "nothing here" as `null` for a list the same way Esplora does.
_none_to_empty_list = BeforeValidator(lambda value: value if isinstance(value, list) else [])


class _JsonRpcLog(ProviderPayload):
    """One log object from a receipt."""

    log_index: Annotated[Any, Field(default=None, alias="logIndex")]
    address: Any = None
    topics: Annotated[tuple[Any, ...], _none_to_empty_list] = ()
    data: Any = None
    removed: bool = False


class _JsonRpcReceipt(ProviderPayload):
    """A transaction receipt, where the fee, the status and the logs live."""

    status: Any = None
    gas_used: Annotated[Any, Field(default=None, alias="gasUsed")]
    effective_gas_price: Annotated[Any, Field(default=None, alias="effectiveGasPrice")]
    contract_address: Annotated[Any, Field(default=None, alias="contractAddress")]
    logs: Annotated[tuple[Mapping[str, Any], ...], _none_to_empty_list] = ()


class _JsonRpcTransaction(ProviderPayload):
    """A transaction object as `eth_getTransactionByHash` returns it.

    **Every quantity is `Any` on purpose, and that is a decision rather than a shortcut.** The
    values a node sends are hex strings read by :func:`parse_hex_int`, which is *tolerant* — it
    answers ``None`` for anything it cannot read. Declaring these `str | None` would move that
    reading into validation, where one quantity the node spelled unexpectedly would refuse the
    whole transaction instead of leaving that one field absent. A shape that made a payload
    *less* tolerant is a shape that changes what the library does.

    So what this declares is the **keys** — which is the half that drifts. A node that renames
    `effectiveGasPrice` used to cost a fee with nothing saying so; here the key is named once, and
    the provider's own spelling is the alias, so the shape reads as what the node sends while the
    attribute reads as this library writes things.
    """

    hash: Any = None
    block_hash: Annotated[Any, Field(default=None, alias="blockHash")]
    block_number: Annotated[Any, Field(default=None, alias="blockNumber")]
    sender: Annotated[Any, Field(default=None, alias="from")]
    to: Any = None
    value: Any = None
    nonce: Any = None
    gas: Any = None
    gas_price: Annotated[Any, Field(default=None, alias="gasPrice")]
    max_fee_per_gas: Annotated[Any, Field(default=None, alias="maxFeePerGas")]
    max_priority_fee_per_gas: Annotated[Any, Field(default=None, alias="maxPriorityFeePerGas")]
    input: Any = None


class _JsonRpcBlock(ProviderPayload):
    """A block object as `eth_getBlockByNumber(full=false)` returns it."""

    hash: Any = None
    number: Any = None
    timestamp: Any = None
    size: Any = None
    parent_hash: Annotated[Any, Field(default=None, alias="parentHash")]
    #: `Any` for the same reason as the quantities above, and one more: the parser distinguishes a
    #: *list* from anything else and reports `tx_count=None` — an unknown count — for the latter,
    #: where an absent key is a count of zero. Typing it as a sequence would collapse those two,
    #: and "this block has no transactions" and "this payload did not say" are different facts.
    transactions: Any = None


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


def method_id_from(data: Any) -> str | None:
    """The four-byte selector of a call, as ``0x`` and eight hex characters, or ``None``.

    Anything shorter than ten characters is not a selector: ``"0x"`` is the empty call, and a
    three-byte input is not a method call at all. Returning the short string instead would put
    something in ``Transaction.method_id`` that a reader would take for a selector and that no
    ABI could resolve.

    **The rule was written twice** — once slicing JSON-RPC's ``input``, once deriving the same
    thing from Etherscan's ``methodId`` — and the second copy carried an extra ``!= "0x"`` test
    the length check already covered. A redundant clause in one of two copies is how two copies
    of a rule start to look deliberate.
    """
    if not isinstance(data, str):
        return None
    return data[:10] if len(data) >= 10 else None


def has_code(code: Any) -> bool:
    """Whether an ``eth_getCode`` answer means code is deployed at the address.

    **``"0x"`` and ``""`` are the two spellings nodes use for "nothing is deployed here"**, and
    reading one as code is an ordinary wallet reported as a contract — a claim about what an
    address *is*, which is the kind a reader acts on and cannot check for themselves.

    The rule was written out twice, in ``jsonrpc_eth.py`` and ``etherscan.py``, which is how two
    copies of a convention come to disagree. Anything that is not a string is not an answer at
    all, and answers "no code" rather than "code", because the failure that matters here is the
    false positive.
    """
    return isinstance(code, str) and code not in ("0x", "")


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
    if len(body) < _ADDRESS_HEX_DIGITS:
        return None
    return address_or_none("0x" + body[-_ADDRESS_HEX_DIGITS:])


def address_to_topic(address: str) -> str:
    """Pad an address to a 32-byte log topic, as ``eth_getLogs`` expects."""
    normalized = normalize_address(address)
    return "0x" + normalized[2:].rjust(_TOPIC_HEX_DIGITS, "0")


def parse_log(raw: Mapping[str, Any], *, provider: str = "json-rpc") -> LogEntry:
    """Parse a JSON-RPC log object."""
    entry = read_payload(_JsonRpcLog, raw, provider=provider, what="log")
    return LogEntry(
        index=parse_hex_int(entry.log_index) or 0,
        address=address_or_none(entry.address),
        topics=tuple(str(topic) for topic in entry.topics),
        data=entry.data,
        removed=entry.removed,
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
    entry = _JsonRpcLog.model_validate(raw)
    topics = entry.topics
    if not topics or not isinstance(topics[0], str):
        return None
    if topics[0].lower() != TRANSFER_TOPIC:
        return None
    if len(topics) != 3:
        return None
    amount = parse_hex_int(entry.data)
    if amount is None:
        return None
    contract = address_or_none(entry.address)
    return Transfer(
        chain=chain,
        asset=AssetRef(chain=chain, kind=AssetKind.ERC20, contract=contract),
        amount=amount,
        txid=txid,
        src=topic_to_address(topics[1]),
        dst=topic_to_address(topics[2]),
        index=parse_hex_int(entry.log_index),
        block_height=block_height,
        timestamp=timestamp,
        via=FlowVia.ERC20,
        provenance=provenance,
    )


def _status_from_receipt(receipt: _JsonRpcReceipt | None) -> TxStatus:
    if receipt is None:
        return TxStatus.PENDING
    if receipt.status == "0x0":
        return TxStatus.FAILED
    if receipt.status == "0x1":
        return TxStatus.CONFIRMED
    return TxStatus.PENDING


def parse_rpc_transaction(
    tx: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    chain: Chain,
    provider: str = "json-rpc",
    provenance: Provenance | None = None,
) -> Transaction:
    """Build a :class:`Transaction` from a JSON-RPC transaction and its receipt.

    The receipt is optional because a pending transaction has none, but it is
    where ``gasUsed``, ``effectiveGasPrice``, ``status`` and the logs live. The fee
    is computed as ``gasUsed * effectiveGasPrice`` (falling back to ``gasPrice``),
    which is what makes the pseudo-UTXO view conserve value on an account chain.
    """
    parsed = read_payload(_JsonRpcTransaction, tx, provider=provider, what="transaction")
    sealed = (
        read_payload(_JsonRpcReceipt, receipt, provider=provider, what="receipt")
        if receipt
        else None
    )

    gas_used = parse_hex_int(sealed.gas_used) if sealed else None
    effective = parse_hex_int(sealed.effective_gas_price) if sealed else None
    gas_price = parse_hex_int(parsed.gas_price)
    price_for_fee = effective if effective is not None else gas_price
    fee = gas_used * price_for_fee if gas_used is not None and price_for_fee is not None else None
    logs = tuple(parse_log(raw, provider=provider) for raw in sealed.logs) if sealed else ()
    input_hex = parsed.input or ""

    return Transaction(
        chain=chain,
        txid=parsed.hash or "",
        status=_status_from_receipt(sealed),
        block_hash=parsed.block_hash,
        block_height=parse_hex_int(parsed.block_number),
        from_address=address_or_none(parsed.sender),
        to_address=address_or_none(parsed.to),
        value=parse_hex_int(parsed.value),
        nonce=parse_hex_int(parsed.nonce),
        gas_limit=parse_hex_int(parsed.gas),
        gas_used=gas_used,
        gas_price=gas_price,
        effective_gas_price=effective,
        max_fee_per_gas=parse_hex_int(parsed.max_fee_per_gas),
        max_priority_fee_per_gas=parse_hex_int(parsed.max_priority_fee_per_gas),
        contract_address=address_or_none(sealed.contract_address) if sealed else None,
        method_id=method_id_from(input_hex),
        logs=logs,
        fee=fee,
        fee_asset=AssetRef.of_native(chain),
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
    entry = read_payload(_JsonRpcBlock, raw, provider=provider, what="block")
    block_hash = entry.hash or ""
    height = parse_hex_int(entry.number)
    if height is None:
        raise SchemaError(provider, f"block {block_hash} payload carries no number")
    transactions = entry.transactions or []
    # ``eth_getBlockByNumber`` with ``full=false`` returns the block's transaction **hashes**, not
    # its transactions — so the list read here for the count also holds the identifiers, and
    # throwing them away would be discarding the only keyless way to get from a block to what is in
    # it. A full node would need ``full=true``, which is a much larger payload for the same ids.
    ids = tuple(str(txid) for txid in transactions) if isinstance(transactions, list) else ()
    return Block(
        chain=chain,
        hash=block_hash,
        height=height,
        timestamp=from_hex_seconds(entry.timestamp),
        tx_count=len(transactions) if isinstance(transactions, list) else None,
        transaction_ids=ids,
        size=parse_hex_int(entry.size),
        # ``weight`` is deliberately left unset: it is a Bitcoin block-weight field
        # and an EVM block's gasUsed means something else entirely. Filing one under
        # the other's name would be worse than omitting it.
        prev_hash=entry.parent_hash,
        provenance=provenance,
    )
