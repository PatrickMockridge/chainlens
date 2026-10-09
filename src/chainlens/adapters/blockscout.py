"""Blockscout: an indexed Ethereum API with no key.

**This adapter exists because Ethereum address history was unreachable.** The only provider that
could list an address's transactions was Etherscan, which needs a credential and forbids
redistributing what it returns — so every Ethereum walk required a key, and no Ethereum walk could
be recorded as a committed fixture. Blockscout speaks the same module/action envelope and asks for
nothing, which removes both constraints at once.

**This provider does not advertise `TX`, and that is the point** — the same sentence
:mod:`chainlens.adapters.jsonrpc_eth` makes about `ADDRESS_TXS`, from the other side. Blockscout
serves the *indexed* half of the Etherscan-compatible surface: the account module and its own v2
address endpoint. Its node RPC is a POST at a different path, and Etherscan's `?module=proxy` shim
— which is where `eth_getTransactionByHash`, `eth_getBlockByNumber` and `eth_getCode` live — returns
HTTP 400 here. So this class declares `ADDRESS`, `BALANCE`, `ADDRESS_TXS`, `TOKEN_TRANSFERS` and
`WINDOW_TRANSFERS`, and refuses the rest by not claiming it rather than by failing at the call.

A caller who needs a transaction by hash composes::

    CompositeProvider([BlockscoutProvider(), JsonRpcEthProvider()])

which routes each question to the provider that can answer it — the arrangement
``docs/plugins/writing-a-provider.md`` describes.

**Two things to know before pointing a corpus walk at this.**

* **The budget is shared.** The hosted instance publishes 300 requests a minute per IP, and that
  bucket is shared across every *unauthenticated* caller of the same instance — so a walk can be
  throttled by other people's traffic, not only by its own. Measured while writing this: a handful
  of exploratory requests was enough to earn ``Too many requests``. The rate limit below is
  declared below the published figure for that reason, and
  :class:`~chainlens.exceptions.RateLimitError` is what a walk surfaces when it is hit.
* **It caps silently, like Etherscan.** ``txlist`` returns at most the 10,000 most recent records
  and does not say so; the walk simply ends, looking exactly like an address with a short history.

The data is public chain data served by a free, keyless, open-source explorer, so
``redistributable`` is ``True`` and its host may be recorded as a cassette — see
``docs/explanation/data-licensing.md``. That flag is a project-level judgement about terms, not
legal advice, and it is the reason this is the first Ethereum adapter whose responses can be
committed as fixtures.
"""

from __future__ import annotations

from typing import Any

from chainlens.adapters._etherscan_api import EtherscanCompatProvider
from chainlens.adapters._evm import parse_decimal_int
from chainlens.adapters._payload import ProviderPayload, read_payload
from chainlens.codec.eth_address import normalize_address
from chainlens.config import Settings
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport

__all__ = ["BlockscoutProvider"]

#: The public instance for Ethereum mainnet. A self-hosted instance works by passing ``base_url``:
#: Blockscout is open-source explorer software, and pointing this at your own copy is the way to
#: have an Ethereum index without anyone else's budget.
_BASE_URL = "https://eth.blockscout.com/"

#: Below the published 300 requests/minute, because that budget is per IP and shared with every
#: other unauthenticated caller of the same instance — which is not the situation a rate limit
#: normally describes, where the budget is yours to spend.
_RATE_LIMIT = RateLimit(requests=3, per=1.0, burst=5)


class _BlockscoutAddress(ProviderPayload):
    """A Blockscout v2 address object — the two fields this library reads from it.

    A model for two fields, for the same reason the other three families have one: the shape
    belongs beside theirs rather than as string keys in a method body. It also removes the only
    place in the package that insisted on ``dict`` where every other adapter accepts any
    ``Mapping`` — a distinction nobody intended, and one with nothing to act on: a payload that
    was a mapping but not a dict was refused here and accepted everywhere else.
    """

    coin_balance: Any = None
    is_contract: Any = None


class BlockscoutProvider(EtherscanCompatProvider):
    """Ethereum via Blockscout, with no credential.

    Args:
        base_url: the instance to read. Defaults to the public Ethereum mainnet one; a self-hosted
            instance or another chain's is why this is a parameter.
        chain: overrides the reported chain, for a Blockscout instance serving a network that is not
            Ethereum mainnet.
    """

    name = "blockscout"
    chain = Chain.ETHEREUM
    base_url = _BASE_URL

    #: Public chain data, served by a free keyless instance of open-source software. See the module
    #: docstring — and note this is the project's judgement about terms, not legal advice.
    redistributable = True

    rate_limit = _RATE_LIMIT

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        chain: Chain | None = None,
        settings: Settings | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self.base_url = base_url
        if chain is not None:
            self.chain = chain
        # No credential to read: that is the whole point of this provider, and a constructor that
        # asked for one would be asking for something this host does not have.
        self._transport = transport or Transport(
            provider_name=self.name,
            base_url=self.base_url,
            settings=self._settings,
            rate_limit=self.rate_limit,
        )

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        """An address, from the v2 endpoint rather than from a JSON-RPC proxy call.

        Etherscan answers this over ``?module=proxy&action=eth_getCode``; Blockscout's equivalent is
        its own address object, which carries richer facts in one request. The two are different
        shapes, which is why this method is not in the shared base.

        ``tx_count`` is left ``None``: the v2 object has no transaction count, and a count would
        have to be paged to exhaustion. Absent beats wrong.
        """
        normalized = normalize_address(address)
        payload = await self._transport.get_json(f"api/v2/addresses/{normalized}")
        entry = read_payload(_BlockscoutAddress, payload, provider=self.name, what="address")
        return Address(
            chain=self.chain,
            address=normalized,
            # A decimal string, not hex — the v2 API renders wei as a decimal number.
            balance=parse_decimal_int(entry.coin_balance),
            is_contract=bool(entry.is_contract),
            provenance=self._provenance("address"),
        )
