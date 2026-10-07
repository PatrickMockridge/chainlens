"""Re-run every on-chain check the label data records, and report what moved.

The corroboration in each label record is a *measurement with a date on it*. This re-takes the
measurement, so that a value which has drifted — coins that moved, a contract that was swept — is
visible as drift rather than sitting in the file looking current forever.

**It is a make target rather than a test**, because it needs the network and the suite runs under
``--block-network``. That is not a compromise: the test asserts that every record *carries* a
corroboration and a date, which is the property that can be checked offline; whether the number is
still right is a question only the chain can answer, and it is asked here.

Run it the way ``make labels-verify`` does::

    uv run python tests/labels/verify_corroboration.py

Exit status is 0 whether or not anything moved — drift is a finding to read, not a failure. A
corroboration that has moved is often the *interesting* thing: the FBI's seized coins were
auctioned, so its balance is lower than when the seizure happened, and that is worth knowing.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime

import anyio

from chainlens.labels.records import DATA_DIR, Corroboration, load_directory
from chainlens.models.enums import Chain
from chainlens.providers.transport import Transport

#: Public, keyless endpoints. Both are free providers, which is what lets this run against them
#: without a credential and without a redistribution question.
MEMPOOL = "https://mempool.space"
ETHEREUM_RPC = "https://ethereum-rpc.publicnode.com"

#: How far a re-measurement may move before it is worth printing. Balances drift by dust as
#: transactions land; a change of more than a few parts per million is a movement, not rounding.
TOLERANCE = 1e-6


def _moved(recorded: float | None, observed: float | None) -> bool:
    if recorded is None or observed is None:
        return False
    scale = max(abs(recorded), 1.0)
    return abs(observed - recorded) / scale > TOLERANCE


async def _bitcoin(transport: Transport, address: str) -> Corroboration:
    """What a UTXO chain can say about an address without an indexer behind it."""
    payload = await transport.get_json(f"api/address/{address}")
    stats = payload.get("chain_stats", {})
    funded = stats.get("funded_txo_sum", 0) / 1e8
    spent = stats.get("spent_txo_sum", 0) / 1e8
    return Corroboration(
        chain=Chain.BITCOIN,
        observed_at=_today(),
        received=funded,
        balance=funded - spent,
        funding_outputs=stats.get("funded_txo_count"),
    )


async def _ethereum(transport: Transport, address: str) -> Corroboration:
    """What a node can say: the balance, and whether there is code there.

    No "received" figure: a node keeps no index of an address's history, which is the same
    limitation ``jsonrpc_eth`` documents for transaction lists.
    """
    balance = await transport.post_json(
        "",
        payload={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBalance",
            "params": [address, "latest"],
        },
    )
    code = await transport.post_json(
        "",
        payload={"jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [address, "latest"]},
    )
    raw_code = code.get("result", "0x")
    return Corroboration(
        chain=Chain.ETHEREUM,
        observed_at=_today(),
        balance=int(balance.get("result", "0x0"), 16) / 1e18,
        is_contract=len(raw_code) > 2,
    )


def _today() -> date:
    """Today, in UTC. The date a measurement was taken belongs to the measurement."""
    return datetime.now(UTC).date()


async def main() -> int:
    bitcoin = Transport(provider_name="mempool", base_url=MEMPOOL)
    ethereum = Transport(provider_name="eth-verify", base_url=ETHEREUM_RPC)
    drifted = 0
    checked = 0
    try:
        for label_file in load_directory(DATA_DIR):
            for record in label_file.labels:
                for address, recorded in record.corroboration.items():
                    observed = (
                        await _bitcoin(bitcoin, address)
                        if recorded.chain is Chain.BITCOIN
                        else await _ethereum(ethereum, address)
                    )
                    checked += 1
                    changes = [
                        f"{field}: {getattr(recorded, field)} -> {getattr(observed, field)}"
                        for field in ("received", "balance", "is_contract", "funding_outputs")
                        if _moved(getattr(recorded, field), getattr(observed, field))
                        or (
                            field == "is_contract"
                            and getattr(recorded, field) != getattr(observed, field)
                        )
                    ]
                    if changes:
                        drifted += 1
                        print(f"MOVED  {record.name} / {address}")
                        for change in changes:
                            print(f"         {change}")
                    else:
                        print(f"ok     {record.name} / {address}")
    finally:
        await bitcoin.aclose()
        await ethereum.aclose()

    print(f"\n{checked} corroboration(s) re-checked, {drifted} moved")
    return 0


if __name__ == "__main__":
    sys.exit(anyio.run(main))
