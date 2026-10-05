# Data licensing

`chainlens` is MIT licensed. **The data you retrieve with it is not.** Several
providers' terms prohibit redistributing their data, and this has concrete
consequences for how the project and its users may behave.

## The rule for this repository

Cassettes and fixtures are committed **only for free providers** whose terms
permit it (mempool.space, Blockstream Esplora, public JSON-RPC endpoints).

Adapters for commercial providers (Etherscan, Blockchair, Glassnode, Dune,
Nansen) are tested with **synthetic fixtures** written by hand, never with
recorded responses. A recorded Etherscan response is Etherscan's data, and
committing it would redistribute it.

If you contribute a cassette for a commercial adapter, expect it to be rejected
in review — not because the test is unwelcome, but because the fixture is.

## The rule for reports

Every provider declares `redistributable`:

```python
from chainlens.testing import InMemoryProvider

InMemoryProvider().redistributable   # True — fixture data we wrote
```

The report generator reads this flag and warns before embedding raw provider
payloads in a report that may be shared. A derived fact ("this address received
12.5 BTC") is generally fine to publish; a verbatim dump of a commercial
provider's response is generally not.

## Secrets

Every commercial provider passes its key as a *query parameter*, so VCR's
`filter_query_parameters` is configured by default in `tests/conftest.py` for
`apikey`, `key`, and `api_key`. Headers are filtered too. A test asserts no
committed cassette contains a key-shaped string.

This is defence in depth: keys should never reach a fixture, and if one does,
the filtering and the test are there to catch it.

## Privacy

On-chain analysis is also a data-protection question, not only a contractual one.
Addresses are often treated as personal data, and an immutable ledger cannot
satisfy an erasure request literally. See
[Forensic limits](forensic-limits.md#privacy).

This page is not legal advice.
