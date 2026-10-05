"""Closed vocabularies shared by the models, codec and analysis layers.

These are deliberately pure ``StrEnum`` definitions with no pydantic import, so
``chainlens.codec`` can depend on the shared vocabulary without dragging in the
model layer. Everything here is stable, serialisable and safe to put on the wire.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

__all__ = [
    "AssetKind",
    "Chain",
    "ChainModel",
    "Confidence",
    "Direction",
    "EntityKind",
    "FlowDirection",
    "FlowVia",
    "LabelSource",
    "ScriptType",
    "TxStatus",
]


class ChainModel(StrEnum):
    """Which ledger model a chain uses.

    This is the discriminator that tells a consumer whether the native fields or
    the synthesized input/output view of a transaction is authoritative.
    """

    UTXO = "utxo"
    ACCOUNT = "account"


class Chain(StrEnum):
    """A supported chain.

    Only the chains this library has first-class knowledge of are enumerated.
    Third-party providers may target others by extending this enum at the edges
    (see the plugin docs) rather than by inventing free-form strings.
    """

    BITCOIN = "bitcoin"
    BITCOIN_TESTNET = "bitcoin_testnet"
    LITECOIN = "litecoin"
    DOGECOIN = "dogecoin"
    BITCOIN_CASH = "bitcoin_cash"
    ETHEREUM = "ethereum"

    @property
    def chain_model(self) -> ChainModel:
        """Whether this chain is UTXO-based or account-based."""
        if self in _UTXO_CHAINS:
            return ChainModel.UTXO
        return ChainModel.ACCOUNT

    @property
    def is_evm(self) -> bool:
        """Whether this chain is EVM-compatible (address/model semantics shared)."""
        return self is Chain.ETHEREUM


_UTXO_CHAINS = frozenset(
    {Chain.BITCOIN, Chain.BITCOIN_TESTNET, Chain.LITECOIN, Chain.DOGECOIN, Chain.BITCOIN_CASH}
)


class AssetKind(StrEnum):
    """The kind of asset a transfer or balance refers to."""

    NATIVE = "native"
    ERC20 = "erc20"
    ERC721 = "erc721"
    ERC1155 = "erc1155"
    OTHER = "other"


class ScriptType(StrEnum):
    """Classification of a Bitcoin output script (scriptPubKey).

    ``NONSTANDARD`` means the script is well-formed hex but matches no known
    template; ``UNKNOWN`` means it could not be parsed at all. The distinction
    matters: a nonstandard output is still spendable and still carries value,
    whereas an unparseable one means the provider sent us something we do not
    understand.
    """

    P2PK = "p2pk"
    P2PKH = "p2pkh"
    P2SH = "p2sh"
    P2WPKH = "p2wpkh"
    P2WSH = "p2wsh"
    P2TR = "p2tr"
    MULTISIG = "multisig"
    OP_RETURN = "op_return"
    NONSTANDARD = "nonstandard"
    UNKNOWN = "unknown"

    @property
    def is_witness(self) -> bool:
        return self in {ScriptType.P2WPKH, ScriptType.P2WSH, ScriptType.P2TR}

    @property
    def has_address(self) -> bool:
        """Whether this script type maps to a standard address form."""
        return self in {
            ScriptType.P2PKH,
            ScriptType.P2SH,
            ScriptType.P2WPKH,
            ScriptType.P2WSH,
            ScriptType.P2TR,
        }


class TxStatus(StrEnum):
    """Confirmation state of a transaction."""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    FAILED = "failed"
    DROPPED = "dropped"


class FlowDirection(StrEnum):
    """Direction of a value flow relative to the thing being traced."""

    IN = "in"
    OUT = "out"
    SELF = "self"


class Direction(StrEnum):
    """Traversal direction requested from the tracer."""

    IN = "in"
    OUT = "out"
    BOTH = "both"


class FlowVia(StrEnum):
    """The mechanism by which value moved.

    ``INTERNAL`` is an EVM internal transfer (value moved by contract execution
    rather than by a top-level transaction); ``CONTRACT`` covers token transfers
    whose sender is a contract. Confusing these with a plain native transfer is a
    common source of incorrect flow totals.
    """

    UTXO = "utxo"
    NATIVE = "native"
    INTERNAL = "internal"
    CONTRACT = "contract"
    ERC20 = "erc20"
    ERC721 = "erc721"
    ERC1155 = "erc1155"
    COINBASE = "coinbase"


class Confidence(StrEnum):
    """A coarse confidence band for reporting.

    Heuristics carry a numeric ``confidence`` in ``[0, 1]``; this band exists so
    reports and human summaries can render a stable vocabulary without inventing
    their own cut-offs.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> Self:
        """Map a numeric confidence onto a band.

        Thresholds are ``>= 0.8`` high, ``>= 0.5`` medium, else low. A heuristic
        that cannot clear the low band should abstain rather than report.
        """
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {score}")
        if score >= 0.8:
            return cls.HIGH
        if score >= 0.5:
            return cls.MEDIUM
        return cls.LOW


class EntityKind(StrEnum):
    """What kind of real-world actor an entity is believed to be."""

    HEURISTIC = "heuristic"
    SERVICE = "service"
    EXCHANGE = "exchange"
    MIXER = "mixer"
    SANCTIONED = "sanctioned"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


class LabelSource(StrEnum):
    """Provenance of a label attached to an address or entity.

    Provenance is what separates "an exchange confirmed this address" from "a
    heuristic guessed it", so it is recorded on every label.
    """

    PROVIDER = "provider"
    USER = "user"
    HEURISTIC = "heuristic"
    IMPORTED = "imported"
