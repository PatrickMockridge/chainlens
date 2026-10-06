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
    "ClaimVerdict",
    "Confidence",
    "Direction",
    "EntityKind",
    "FlowDirection",
    "FlowVia",
    "LabelSource",
    "Proposition",
    "ScriptType",
    "TxStatus",
    "VerbalScale",
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


class ClaimVerdict(StrEnum):
    """The categorical finding about a claim.

    Deliberately about the *match structure* rather than about probability. The
    likelihood ratio is a separate quantity attached alongside; deriving a verdict
    from it would conflate "what the chain shows" with "how much that is worth",
    which the verification layer keeps strictly apart.

    Three members, and the third is not a finding about the claim at all: it says nothing was
    decided, and *why* is carried on the finding's
    :attr:`~chainlens.verify.verdicts.VerificationFinding.gap` — an input with no value, which
    knows whether nothing here could obtain it (``no_method``), whether something could and the
    data was not reachable (``no_data``), or whether nobody asked (``not_requested``).

    The two were separate members once, ``UNVERIFIABLE`` and ``INSUFFICIENT_DATA``, on the
    argument that they mean opposite things to a reader — stop asking versus configure
    something. That argument was right and it is why the kinds exist; what was wrong was
    spelling it twice. A verdict is either decided or it is not, and the reason it is not is a
    property of an input rather than a fourth way for a claim to come out.
    """

    #: Chain data is consistent with the claim.
    SUPPORTED = "supported"
    #: Chain data contradicts it, including an unparseable identifier.
    CONTRADICTED = "contradicted"
    #: Nothing decided the claim, and the finding's ``gap`` says what is missing and of which
    #: kind. Never a statement about the claim: it is not evidence for it, and not against it.
    UNRESOLVED = "unresolved"

    @property
    def is_informative(self) -> bool:
        """Whether this verdict decided the claim, as opposed to admitting it could not.

        One definition, because three places ask — a finding, a report, and a derivation — and
        each used to spell out ``in {SUPPORTED, CONTRADICTED}`` for itself. With the third
        member meaning "nothing decided", the predicate *is* that negation, and writing it that
        way is what keeps a fourth verdict from being quietly informative.
        """
        return self is not ClaimVerdict.UNRESOLVED


class Proposition(StrEnum):
    """Which of two competing propositions a likelihood ratio supports."""

    #: The claim is true -- the observed transfer is the specific payment asserted.
    FIRST = "first"
    #: The claim is false -- the match arose by coincidence, or by something other
    #: than the asserted payment.
    ALTERNATIVE = "alternative"
    #: LR of 1: the evidence does not distinguish the two at all.
    NEITHER = "neither"


class VerbalScale(StrEnum):
    """Belief in a proposition, on the ENFSI verbal scale.

    Taken from the appendix of the *ENFSI Guideline for Evaluative Reporting in
    Forensic Science* (2015). The guideline treats the verbal scale as optional
    and jurisdiction-dependent and prefers the numeric ratio where one can be
    given, so the boundaries behind these bands are configurable -- see
    :class:`~chainlens.verify.scale.VerbalThresholds` -- and these labels are the
    default rather than a universal standard.
    """

    #: The findings do not distinguish the propositions (LR exactly 1).
    NONE = "none"
    #: 1 < LR <= 10. The guideline's "slight / limited support".
    SLIGHT = "slight"
    #: 10 < LR <= 100.
    MODERATE = "moderate"
    #: 100 < LR <= 1000.
    MODERATELY_STRONG = "moderately strong"
    #: 1000 < LR <= 10000.
    STRONG = "strong"
    #: LR > 10000.
    VERY_STRONG = "very strong"

    @property
    def rank(self) -> int:
        """Position on the scale, for comparison and for spanning checks.

        ``NONE`` is 0, so an interval whose bands span a range can be compared by
        rank without string manipulation.
        """
        return _VERBAL_ORDER.index(self)


_VERBAL_ORDER: tuple[VerbalScale, ...] = (
    VerbalScale.NONE,
    VerbalScale.SLIGHT,
    VerbalScale.MODERATE,
    VerbalScale.MODERATELY_STRONG,
    VerbalScale.STRONG,
    VerbalScale.VERY_STRONG,
)
