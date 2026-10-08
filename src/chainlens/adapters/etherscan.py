"""Etherscan API V2.

One key covers 50+ EVM chains via a ``chainid`` parameter, so "add a chain" for an
EVM network is usually a chain id rather than a new adapter.

The module/action envelope, its three parsers and the paging are shared with every other host that
speaks the same protocol — see :mod:`chainlens.adapters._etherscan_api`. What is left here is what
is Etherscan's own: the credential, the terms that forbid redistributing its data, the free-tier
budget, and the ``proxy`` module.

:**The ``proxy`` module is why this is not just a base URL.** Etherscan answers "what is this
transaction", "what is this block" and "is there code at this address" over a JSON-RPC shim at
``?module=proxy``. Hosts that copy the flat API generally do **not** copy that, so those three
capabilities live here and only here — see :mod:`chainlens.adapters.blockscout` for the keyless
alternative and what it deliberately does not advertise.

Requires ``ETHERSCAN_API_KEY``. The key is read from settings, never from a function argument.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chainlens.adapters._etherscan_api import EtherscanCompatProvider
from chainlens.adapters._evm import parse_rpc_block, parse_rpc_transaction
from chainlens.codec.eth_address import normalize_address
from chainlens.config import Settings
from chainlens.exceptions import ConfigurationError, NotFoundError
from chainlens.models.base import Provenance
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, Block, Transaction
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport, read_provenance

__all__ = ["EtherscanProvider"]

#: Base URL ends at /v2/ so the request path "api" produces exactly /v2/api.
_API_BASE = "https://api.etherscan.io/v2/"

#: Free-tier budget. The per-second limit is shared across every chain.
_FREE_TIER = RateLimit(requests=5, per=1.0, daily=100_000)


class EtherscanProvider(EtherscanCompatProvider):
    """Ethereum (and any EVM chain Etherscan V2 serves) via the Etherscan API.

    Args:
        chain_id: the EVM chain id, 1 for Ethereum mainnet. This is the knob that
            makes another EVM chain work without a new adapter.
        chain: overrides the reported chain, for when a ``Chain`` member exists for
            the target network.
    """

    name = "etherscan"
    chain = Chain.ETHEREUM
    base_url = _API_BASE

    #: Etherscan's terms prohibit redistributing their data, so their responses are
    #: never committed as fixtures. See docs/explanation/data-licensing.md.
    redistributable = False

    rate_limit = _FREE_TIER

    def __init__(
        self,
        *,
        chain_id: int = 1,
        chain: Chain | None = None,
        settings: Settings | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self._chain_id = chain_id
        if chain is not None:
            self.chain = chain

        api_key = self._settings.api_key("etherscan")
        if not api_key:
            raise ConfigurationError(
                "etherscan requires an API key; set ETHERSCAN_API_KEY in the "
                "environment or a .env file (a free key is sufficient)"
            )
        self._api_key = api_key

        self._transport = transport or Transport(
            provider_name=self.name,
            base_url=self.base_url,
            settings=self._settings,
            rate_limit=self.rate_limit,
        )

    def _request_params(self) -> dict[str, Any]:
        """Every call names the chain, which is the whole point of API V2."""
        return {"chainid": self._chain_id, "apikey": self._api_key}

    def _provenance(self, endpoint: str) -> Provenance:
        return read_provenance(
            self.name, endpoint=f"{self.base_url}api#{self._chain_id}/{endpoint}"
        )

    async def _proxy(self, action: str, **params: Any) -> Any:
        return await self._call("proxy", action, **params)

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        normalized = normalize_address(address)
        balance = await self.get_balance(normalized)
        # Etherscan has no cheap transaction count: txlist would have to be paged to
        # exhaustion. Leaving it None is honest; a wrong count is not.
        code = await self._proxy("eth_getCode", address=normalized, tag="latest")
        is_contract = isinstance(code, str) and code not in ("0x", "")
        return Address(
            chain=self.chain,
            address=normalized,
            balance=balance.amount,
            is_contract=is_contract,
            provenance=self._provenance("address"),
        )

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        tx = await self._proxy("eth_getTransactionByHash", txhash=txid)
        if not isinstance(tx, Mapping):
            raise NotFoundError(self.name, f"transaction {txid!r} not found")
        receipt = await self._proxy("eth_getTransactionReceipt", txhash=txid)
        receipt_map = receipt if isinstance(receipt, Mapping) else None
        return parse_rpc_transaction(
            tx,
            receipt_map,
            chain=self.chain,
            provenance=self._provenance(f"tx/{txid}"),
        )

    @provides(Capability.BLOCK)
    async def get_block(self, reference: str | int) -> Block:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            tag = hex(int(reference))
            raw = await self._proxy("eth_getBlockByNumber", tag=tag, boolean="false")
        else:
            raw = await self._proxy("eth_getBlockByHash", tag=reference, boolean="false")
        if not isinstance(raw, Mapping):
            raise NotFoundError(self.name, f"block {reference!r} not found")
        return parse_rpc_block(
            raw,
            chain=self.chain,
            provider=self.name,
            provenance=self._provenance(f"block/{reference}"),
        )
