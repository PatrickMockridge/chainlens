"""From what a post said to what can be priced.

The bridge between :mod:`chainlens.verify.schema` — text, as written, as a model
reported it — and :mod:`chainlens.verify.claims` — integers, addresses and bands
that arithmetic can run on. Everything here is deterministic, and it is the only
place the two vocabularies meet.

Two deliberate refusals:

* **Amounts are parsed by us.** ``amount_text`` is text, and turning it into base
  units is this module's job. A model never gets to hand us a number, because a
  model that turns "40,000" into 40000 sats produces a finding that looks
  authoritative and is wrong by a factor of 10⁸.
* **A parse failure is not a contradiction.** A claim whose amount cannot be read,
  or whose address fails its checksum, is refused here and reported as short of
  data — it is a statement about *us*, not about the chain, and the difference is
  what keeps a false claim from being dismissed for the wrong reason.

The tolerance is the one number in this module that is a convention rather than a
reading. It is set out loudly in :data:`HEDGE_TOLERANCE` because it is the largest
free parameter in the whole calculation, and it moves the likelihood ratio
roughly linearly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from chainlens.codec import address_to_script, is_valid_address, normalize_address
from chainlens.keycard import SHIPPED
from chainlens.models.enums import Chain
from chainlens.models.primitives import AssetRef
from chainlens.verify.claims import AmountBand, ClaimElements
from chainlens.verify.schema import Claim, ClaimType
from chainlens.vocabulary import row_for

__all__ = [
    "HEDGE_TOLERANCE",
    "AmountReading",
    "ParsedClaim",
    "normalise_address",
    "parse_amount",
    "parse_claim",
]

#: How much wider a hedge word makes the band, as a fraction of the amount.
#:
#: "approximately 40,000 BTC" is not a claim about 40,000 BTC; it is a claim about
#: a neighbourhood, and the width of that neighbourhood is not stated. A real
#: extraction cannot recover it, so this library fixes it at 5% and says so. It is
#: a **convention, not a measurement** — the assumptions list of every finding
#: names it, and the sensitivity analysis sweeps it — because it is the largest
#: free parameter in the calculation and hiding it would be the difference between
#: a stated model and an invented number.
#: Read from the shipped keycard rather than written here. The value is the same number; what
#: changes is that it has one home, and that a caller holding a card can see which value produced
#: the finding in front of them.
HEDGE_TOLERANCE: float = SHIPPED.resolved_thresholds.hedge_tolerance

_HEDGE_WORDS = (
    "about",
    "approximately",
    "approx",
    "around",
    "roughly",
    "circa",
    "nearly",
    "almost",
    "some",
    "~",
)

_AT_LEAST_WORDS = (
    "over",
    "above",
    "exceeding",
    "exceeds",
    "at least",
    "more than",
    "greater than",
    "upwards of",
)


def _word_matcher(words: tuple[str, ...]) -> re.Pattern[str]:
    """A matcher for whole words and set phrases.

    Boundaries rather than plain substring search: "some" appears inside
    "something", and "over" inside "leftover". Reading either as a hedge would
    widen the band — and so move the likelihood ratio — on the strength of an
    unrelated word.
    """
    body = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![a-z])(?:{body})(?![a-z])", re.IGNORECASE)


_HEDGE = _word_matcher(_HEDGE_WORDS)
_AT_LEAST = _word_matcher(_AT_LEAST_WORDS)

#: An explicit plus-or-minus, which is a stated tolerance rather than a hedged one.
_EXPLICIT_TOLERANCE = re.compile(r"(?:±|\+/-|\+-)\s*(?P<tolerance>[\d.,_]+)")

#: A number, an optional magnitude shorthand, then the unit it is counted in. The
#: separator class admits the comma, the underscore and the space as thousands
#: separators, because all three appear in real posts.
_AMOUNT = re.compile(
    r"(?P<number>\d[\d,_ ]*(?:\.\d+)?)\s*(?P<magnitude>[kKmM])?\s*(?P<unit>[A-Za-z]{2,10})",
)

#: Shorthand magnitudes. "40k BTC" is how a post writes forty thousand, and
#: refusing it would drop a claim on a formatting detail.
_MAGNITUDES: dict[str, Decimal] = {"k": Decimal(1_000), "m": Decimal(1_000_000)}

#: Unit token -> chain. **The symbol and the decimals are not here**, and they used to be: this
#: table spelled out `"BTC", 8` four times and `"ETH", 18` five times, in the one module whose
#: job is to *read* a number out of a post. What a unit token tells us is *which chain* the post
#: is talking about; what a bitcoin's decimals are is the vocabulary table's row, and the symbol
#: is the row's too, so the two are read from there rather than restated here.
#:
#: Only the chains this library prices are named; anything else is a claim we cannot check
#: rather than a guess.
_UNITS: dict[str, Chain] = {
    "btc": Chain.BITCOIN,
    "bitcoin": Chain.BITCOIN,
    "bitcoins": Chain.BITCOIN,
    "xbt": Chain.BITCOIN,
    "eth": Chain.ETHEREUM,
    "ethereum": Chain.ETHEREUM,
    "ether": Chain.ETHEREUM,
    "ethers": Chain.ETHEREUM,
}

#: Units that already count base units, so no scaling is applied.
_BASE_UNITS: dict[str, Chain] = {
    "sat": Chain.BITCOIN,
    "sats": Chain.BITCOIN,
    "satoshi": Chain.BITCOIN,
    "satoshis": Chain.BITCOIN,
    "wei": Chain.ETHEREUM,
}


@dataclass(frozen=True, slots=True)
class AmountReading:
    """An amount as *our* code read it.

    Attributes:
        asset: the asset the amount is counted in.
        band: the amount and the tolerance around it.
        hedged: whether a hedge word widened the band.
        tolerance_rule: how the tolerance was arrived at, for the assumptions list.
            Reported rather than inferred later, because a reader is entitled to
            know that "±5% because the post said approximately" is a convention of
            this library and not something the post specified.
    """

    asset: AssetRef
    band: AmountBand
    hedged: bool
    tolerance_rule: str


def normalise_address(address: str, chain: Chain) -> str | None:
    """The canonical form of ``address`` on ``chain``, or ``None`` if it is not one.

    Ethereum addresses are validated by their EIP-55 checksum when they carry one;
    Bitcoin addresses by their base58 or bech32 checksum. An address that fails is
    not a contradiction of the claim — it means the post's address cannot be
    looked up, which is a fact about our reach, not about the chain.
    """
    try:
        if chain.is_evm:
            return normalize_address(address) if is_valid_address(address) else None
        address_to_script(address)
    except (ValueError, TypeError):
        return None
    return address


def _chain_from_address(address: str) -> Chain | None:
    """The chain an address unambiguously belongs to, if any."""
    if address.startswith(("0x", "0X")):
        return Chain.ETHEREUM if is_valid_address(address) else None
    if normalise_address(address, Chain.BITCOIN) is not None:
        return Chain.BITCOIN
    return None


def _quantise(value: Decimal, decimals: int) -> int | None:
    """Scale a decimal amount into base units, refusing sub-unit precision.

    ``None`` rather than a rounded value: rounding 0.000000001 BTC up to one
    satoshi would turn a claim that cannot be checked into one that can, with a
    number we invented.
    """
    scaled = value * (10**decimals)
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)


def parse_amount(text: str) -> AmountReading | None:
    """Read an amount, its asset and its tolerance out of the text a claim used.

    ``None`` when nothing priceable is there — an unstated asset, a chain this
    library does not price, or a sub-unit amount.

    Args:
        text: the amount as written, e.g. ``"more than 40,000 BTC"``.
    """
    match = _AMOUNT.search(text)
    if match is None:
        return None

    unit = match.group("unit").lower()
    # The unit token says *which chain* the post is talking about. The vocabulary table says
    # everything else about the asset — its symbol, its decimals — so none of that is written
    # in this module any more.
    base = unit in _BASE_UNITS
    on_chain = _BASE_UNITS[unit] if base else _UNITS.get(unit)
    if on_chain is None:
        return None
    row = row_for(on_chain)
    chain = Chain(row.chain)
    symbol = row.symbol
    decimals = row.decimals
    # "10 sats" already counts base units, so the number as written is scaled by nothing;
    # "1.5 BTC" is scaled by the row's decimals.
    scale = 0 if base else decimals

    try:
        written = Decimal(re.sub(r"[,_ ]", "", match.group("number")))
    except InvalidOperation:  # pragma: no cover - the regex admits only digits
        return None
    written *= _MAGNITUDES.get((match.group("magnitude") or "").lower(), Decimal(1))

    nominal = _quantise(written, scale)
    if nominal is None or nominal < 0:
        return None

    at_least = _AT_LEAST.search(text) is not None
    hedged = _HEDGE.search(text) is not None

    explicit = _EXPLICIT_TOLERANCE.search(text)
    if explicit is not None:
        try:
            tolerance_value = Decimal(re.sub(r"[,_ ]", "", explicit.group("tolerance")))
        except InvalidOperation:  # pragma: no cover - the regex admits only digits
            return None
        tolerance = _quantise(tolerance_value, scale)
        if tolerance is None:
            return None
        rule = "explicit +/- on the amount as written"
    elif at_least:
        # A lower bound says nothing about the upper side, so the tolerance is not
        # widened: it marks where the band opens, not how wide it is.
        tolerance = 0
        rule = "one-sided claim; the band is open above the stated bound"
    elif hedged:
        tolerance = round(nominal * HEDGE_TOLERANCE)
        rule = (
            f"hedge word in the claim; band widened by {HEDGE_TOLERANCE:.0%} of the "
            "amount, which is a convention of this library and not a stated precision"
        )
    else:
        tolerance = 0
        rule = "amount stated exactly, with no hedge word and no stated tolerance"

    asset = AssetRef.native(chain, symbol=symbol, decimals=decimals)
    band = AmountBand(nominal=nominal, tolerance=tolerance, asset=asset, at_least=at_least)
    return AmountReading(asset=asset, band=band, hedged=hedged, tolerance_rule=rule)


@dataclass(frozen=True, slots=True)
class ParsedClaim:
    """A claim reduced to what can be run against chain data, or the reason it could not be.

    Attributes:
        elements: the priceable elements, or ``None`` when the claim could not be
            reduced.
        notes: why, and any convention that was applied on the way. Always reported:
            a reader has to be able to tell "the claim says nothing checkable" from
            "we could not read what it said".
    """

    elements: ClaimElements | None
    notes: tuple[str, ...] = ()

    @property
    def is_priceable(self) -> bool:
        """Whether the claim reduced to elements an analysis can run against."""
        return self.elements is not None


def parse_claim(claim: Claim) -> ParsedClaim:
    """Reduce one extracted claim to priceable elements.

    The chain comes from the amount's unit when the claim states one, and from the
    address format otherwise — an Ethereum address is recognisable on sight, and
    an entity or label claim names no amount at all.

    A claim that names neither a recipient nor an amount is *refused* here rather
    than passed on: its coincidence probability is exactly 1, so it can carry no
    evidential weight, and pricing it would produce a number that means nothing.
    The refusal is a note, not an error — the claim still gets its categorical
    verdict.
    """
    if claim.type is ClaimType.UNSUPPORTED:
        return ParsedClaim(elements=None, notes=("claim type is not checkable here",))

    notes: list[str] = []
    reading = parse_amount(claim.amount_text) if claim.amount_text else None
    if claim.amount_text and reading is None:
        notes.append(
            f"the amount {claim.amount_text!r} could not be read as a supported asset "
            "amount, so the claim was priced on its addresses alone"
        )

    chain = reading.asset.chain if reading is not None else None
    if chain is None:
        for candidate in claim.addresses:
            chain = _chain_from_address(candidate)
            if chain is not None:
                break
    if chain is None:
        reason = (
            "no address the library recognises and no priceable amount"
            if claim.addresses
            else "the claim names no address and no priceable amount"
        )
        return ParsedClaim(elements=None, notes=(*notes, reason))

    if not claim.addresses:
        return ParsedClaim(
            elements=None,
            notes=(*notes, "the claim names no address to check, only an amount"),
        )

    resolved: list[str] = []
    for candidate in claim.addresses:
        normalised = normalise_address(candidate, chain)
        if normalised is None:
            notes.append(
                f"the address {candidate!r} is not a valid {chain.value} address, so it "
                "cannot be looked up; this is a limit on what we can reach, not a "
                "contradiction of the claim"
            )
            continue
        resolved.append(normalised)

    if not resolved:
        return ParsedClaim(elements=None, notes=tuple(notes))

    asset = reading.asset if reading is not None else AssetRef.native(chain)
    try:
        elements = ClaimElements(
            chain=chain,
            asset=asset,
            sender=resolved[0],
            recipient=resolved[1] if len(resolved) > 1 else None,
            band=reading.band if reading is not None else None,
            window=claim.window,
        )
    except ValueError as exc:
        # The only refusals ``ClaimElements`` raises are the two that mean "there is
        # nothing here to price", and both are findings rather than errors.
        return ParsedClaim(elements=None, notes=(*notes, str(exc)))

    if reading is not None:
        notes.append(f"amount tolerance: {reading.tolerance_rule}")
    return ParsedClaim(elements=elements, notes=tuple(notes))
