"""Model factories for writing tests.

Small, explicit constructors so a test can build a realistic transaction without
spelling out fifteen keyword arguments. Kept in the shipped package (not in
``tests/``) because plugin authors need them too.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import Chain, FlowVia, TxStatus
from chainlens.models.primitives import (
    AssetRef,
    Transaction,
    Transfer,
    TxInput,
    TxOutput,
)

__all__ = [
    "btc_transaction",
    "eth_transaction",
    "inp",
    "make_provenance",
    "out",
    "transfer",
]


def inp(
    index: int,
    address: str | None,
    value: int | None = None,
    *,
    prev_txid: str | None = None,
    prev_vout: int | None = None,
    is_coinbase: bool = False,
) -> TxInput:
    """Build a transaction input."""
    return TxInput(
        index=index,
        address=address,
        value=value,
        prev_txid=prev_txid,
        prev_vout=prev_vout,
        is_coinbase=is_coinbase,
    )


def out(index: int, address: str | None, value: int | None) -> TxOutput:
    """Build a transaction output."""
    return TxOutput(index=index, address=address, value=value)


def btc_transaction(
    txid: str,
    outputs: Iterable[TxOutput],
    inputs: Iterable[TxInput] = (),
    *,
    chain: Chain = Chain.BITCOIN,
    block_height: int | None = None,
    block_time: datetime | None = None,
    fee: int | None = None,
    is_coinbase: bool = False,
    provenance: Provenance | None = None,
) -> Transaction:
    """Build a UTXO-chain transaction."""
    return Transaction(
        chain=chain,
        txid=txid,
        status=TxStatus.CONFIRMED if block_height is not None else TxStatus.PENDING,
        block_height=block_height,
        block_time=block_time,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        fee=fee,
        fee_asset=AssetRef.native(chain, symbol="BTC"),
        is_coinbase=is_coinbase,
        provenance=provenance,
    )


def eth_transaction(
    txid: str,
    from_address: str,
    to_address: str | None,
    value: int,
    *,
    chain: Chain = Chain.ETHEREUM,
    block_height: int | None = None,
    block_time: datetime | None = None,
    fee: int | None = None,
    gas_used: int | None = None,
    gas_price: int | None = None,
    status: TxStatus = TxStatus.CONFIRMED,
    provenance: Provenance | None = None,
) -> Transaction:
    """Build an account-chain transaction.

    Inputs and outputs are left empty on purpose: the model lifts them into the
    canonical view itself, which is the behaviour worth exercising.
    """
    return Transaction(
        chain=chain,
        txid=txid,
        status=status,
        block_height=block_height,
        block_time=block_time,
        from_address=from_address,
        to_address=to_address,
        value=value,
        fee=fee,
        gas_used=gas_used,
        gas_price=gas_price,
        provenance=provenance,
    )


def transfer(
    src: str | None,
    dst: str | None,
    amount: int,
    *,
    txid: str,
    chain: Chain = Chain.BITCOIN,
    via: FlowVia = FlowVia.NATIVE,
    asset: AssetRef | None = None,
    timestamp: datetime | None = None,
    is_change: bool = False,
    index: int | None = None,
) -> Transfer:
    """Build a single value movement."""
    return Transfer(
        chain=chain,
        src=src,
        dst=dst,
        amount=amount,
        txid=txid,
        via=via,
        asset=asset or AssetRef.native(chain),
        timestamp=timestamp,
        is_change=is_change,
        index=index,
    )


def make_provenance(provider: str = "test", **kwargs: object) -> Provenance:
    """A provenance record for fixture data."""
    return Provenance(provider=provider, fetched_at=utcnow(), **kwargs)  # type: ignore[arg-type]
