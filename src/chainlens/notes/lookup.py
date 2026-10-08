"""Asking the chain about every address a corpus mentions.

**This is the first-order pass, and it does not involve a model.** A corpus is full of
address-shaped strings, and :func:`~chainlens.notes.addresses.address_mentions` finds them
deterministically — it is a regex and the library's own validator, so it cannot hallucinate and it
does not need an endpoint. Feeding those straight to a provider is what turns a pile of screenshots
into facts about the chain, and it is upstream of anything a model might contribute.

The ordering matters and is the point: **addresses first, claims second.** A model reading a
screenshot is asked to say what the screenshot asserts, which is a hard task a small model does
badly — the corpus this was written for produced sixty-six "identity" claims about table cells.
Asking the chain about the addresses themselves needs no judgement at all, and every answer is a
number a provider returned.

**What each chain can answer without a key is different, and this says so rather than hiding it.**

* **Bitcoin** has an address index in the free Esplora endpoints: balance, transaction count, and
  first and last seen are all one call.
* **Ethereum** does not. A JSON-RPC node answers a balance and whether there is code at the
  address — which is genuinely useful, and is how a named contract is told from an address typed
  into a table — but "list every transaction this address made" needs an indexer, and the one this
  library can reach is Etherscan, which needs a key.

So a lookup reports what it got and, where it got less than the chain could give, says which
capability was missing. A gap in the setup and a quiet address are different findings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import anyio
from pydantic import AwareDatetime, Field

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel, utcnow
from chainlens.models.enums import Chain
from chainlens.notes.addresses import AddressMention
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability

__all__ = [
    "DEFAULT_LOOKUP_CONCURRENCY",
    "AddressLookup",
    "LookupReport",
    "lookup_addresses",
    "summarise",
]

#: How many addresses are in flight at once.
#:
#: Small, because every free endpoint here publishes a courtesy budget and the provider layer paces
#: requests through a token bucket anyway — this only stops a hundred sockets being opened to wait
#: in that queue.
DEFAULT_LOOKUP_CONCURRENCY = 4


class AddressLookup(LensModel):
    """What the chain said about one address, and where the address came from.

    Attributes:
        address: the canonical address that was queried.
        chain: which chain it was queried on.
        notes: every note that mentioned it. A list rather than one path because the same address
            appearing in four screenshots is one compound fact, and splitting it into four records
            would make a reader look up the same balance four times.
        provider: which provider answered.
        observed_at: when. A balance without a date is a claim about the past made in the present,
            which is the same rule the label corroborations follow.
        balance: what the address holds, in the chain's base unit, or ``None`` when the provider
            could not say.
        is_contract: whether there is code at the address. Checkable on an account chain, and how a
            named contract is told from an address merely typed into a document.
        tx_count: how many transactions the address has been in. ``None`` on a chain whose free
            providers have no index.
        first_seen: the earliest activity, when a provider reports one.
        last_seen: the most recent.
        unreadable: why nothing could be asked, in words, or ``None`` when the lookup worked.
    """

    address: str
    chain: Chain
    notes: tuple[str, ...] = ()
    provider: str
    observed_at: AwareDatetime = Field(default_factory=utcnow)
    balance: int | None = None
    is_contract: bool | None = None
    tx_count: int | None = None
    first_seen: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None
    unreadable: str | None = None

    @property
    def answered(self) -> bool:
        """Whether the chain said anything at all."""
        return self.unreadable is None

    def format(self) -> str:
        """One line for a person, which is what a command prints."""
        if not self.answered:
            return f"{self.address}  —  {self.unreadable}"
        bits = [f"{self.address}"]
        if self.is_contract:
            bits.append("contract")
        if self.balance is not None:
            bits.append(f"balance {self.balance}")
        if self.tx_count is not None:
            bits.append(f"{self.tx_count} txs")
        if self.last_seen is not None:
            bits.append(f"last seen {self.last_seen:%Y-%m-%d}")
        return "  ".join(bits)


class LookupReport(LensModel):
    """Every address one corpus holds, and what the chain said about each.

    A document rather than a list, so it carries which corpus it came from and when it was made. A
    set of balances with no date and no provenance is a set of claims about the past; this is a
    reading with a timestamp, and the two are different artifacts.

    Attributes:
        corpus: the directory the addresses were read from.
        lookups: one entry per distinct address, in the order the corpus mentions them.
        generated_at: when the chain was asked.
    """

    corpus: str = ""
    lookups: tuple[AddressLookup, ...] = ()
    generated_at: AwareDatetime = Field(default_factory=utcnow)


async def lookup_addresses(
    mentions: Sequence[AddressMention],
    *,
    providers: Mapping[Chain, Provider],
    concurrency: int = DEFAULT_LOOKUP_CONCURRENCY,
) -> tuple[AddressLookup, ...]:
    """Ask the chain about every usable address a corpus mentioned.

    One lookup per *distinct* address, however many notes mention it: the chain answer is about the
    address, and asking four times would cost four times as much to produce four copies of one
    fact. Which notes mentioned it is carried on the result instead.

    A chain with no provider in ``providers`` yields lookups marked unreadable rather than being
    dropped, for the reason the corpus layer reports what it could not read: a list of sixteen
    answers from nineteen addresses, with the missing three invisible, is a list that overstates
    what is known.

    Args:
        mentions: what the corpus held. Only the usable ones are queried, and the unusable ones are
            not represented here at all — the caller already has them, with their reasons.
        providers: one provider per chain, chosen by the caller. Which provider answers a chain is
            a configuration question and is deliberately not decided here.
        concurrency: how many lookups are in flight at once.
    """
    grouped: dict[tuple[Chain, str], list[str]] = {}
    order: list[tuple[Chain, str]] = []
    for mention in mentions:
        if not mention.usable or mention.address is None or mention.chain is None:
            continue
        key = (mention.chain, mention.address)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        if mention.note not in grouped[key]:
            grouped[key].append(mention.note)

    results: dict[tuple[Chain, str], AddressLookup] = {}
    semaphore = anyio.Semaphore(concurrency)

    async def run(chain: Chain, address: str) -> None:
        async with semaphore:
            results[(chain, address)] = await _lookup_one(
                chain, address, notes=tuple(grouped[(chain, address)]), providers=providers
            )

    async with anyio.create_task_group() as task_group:
        for chain, address in order:
            task_group.start_soon(run, chain, address)

    # In the order the addresses appear in the corpus, so a reader can follow the list back to the
    # material — the same rule `address_mentions` follows, and for the same reason.
    return tuple(results[key] for key in order)


async def _lookup_one(
    chain: Chain,
    address: str,
    *,
    notes: tuple[str, ...],
    providers: Mapping[Chain, Provider],
) -> AddressLookup:
    """One address, or the reason there is nothing to say about it.

    Nothing here raises. A provider that is down, a chain nobody configured, a call that fails: each
    is a fact about *this* address, and the record carries it, because one unreachable endpoint must
    not cost the other thirty-two.
    """
    provider = providers.get(chain)
    if provider is None:
        return AddressLookup(
            address=address,
            chain=chain,
            notes=notes,
            provider="none",
            unreadable=(
                f"no provider is configured for {chain.value}, so this address was not looked up; "
                "configure one and run this again"
            ),
        )
    if not provider.supports(Capability.ADDRESS):
        return AddressLookup(
            address=address,
            chain=chain,
            notes=notes,
            provider=provider.name,
            unreadable=f"provider {provider.name!r} cannot read an address",
        )
    try:
        view = await provider.get_address(address)
    except ChainlensError as exc:
        # A failed lookup is not a finding about the address: a provider that does not index a
        # chain, or is down, says nothing about whether the address exists.
        return AddressLookup(
            address=address,
            chain=chain,
            notes=notes,
            provider=provider.name,
            unreadable=f"{provider.name} could not answer: {exc}",
        )
    return AddressLookup(
        address=address,
        chain=chain,
        notes=notes,
        provider=provider.name,
        balance=await _balance(provider, address),
        is_contract=view.is_contract,
        tx_count=view.tx_count,
        first_seen=view.first_seen,
        last_seen=view.last_seen,
    )


async def _balance(provider: Provider, address: str) -> int | None:
    """The balance in base units, or ``None`` when the provider cannot say.

    Its own call rather than a field of the address view, because the two capabilities are separate
    and a provider may honestly have one without the other. Its own try, too: a balance that failed
    must not lose the contract check that succeeded.
    """
    if not provider.supports(Capability.BALANCE):
        return None
    try:
        return (await provider.get_balance(address)).amount
    except ChainlensError:
        return None


def summarise(lookups: Sequence[AddressLookup]) -> str:
    """One line: how many answered, how many did not, and how many were contracts."""
    answered = [item for item in lookups if item.answered]
    contracts = sum(1 for item in answered if item.is_contract)
    line = f"{len(answered)}/{len(lookups)} address(es) answered"
    if contracts:
        line += f", {contracts} of them contracts"
    if len(answered) != len(lookups):
        line += f"; {len(lookups) - len(answered)} could not be looked up"
    return line
