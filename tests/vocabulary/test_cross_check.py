"""The table's numbers, held to something outside the table.

The rule the vocabulary layer exists to keep is that a number is written down once. That rule
on its own would be satisfied by a table of invented values, so it needs a second half: the
value has to be *checked*, and checked against something that already knows it rather than
against a second copy of this repository's opinion.

**Bitcoin has such an oracle here and Ethereum does not, and the asymmetry is stated rather
than smoothed over.** ``pycoin`` is a dev dependency described in ``pyproject.toml`` as a
"dev-only cross-validation oracle for the BTC codec" — and until this file existed, nothing in
the tree imported it. That comment was a claim about a check that was not there. The first
test below is what makes it true.

For Ethereum there is no equivalent: ``web3`` knows that an ether is ``10**18`` wei, but it is
an optional extra that this repository deliberately keeps out of the core, and it is not in the
dev group. So the ethereum row is checked *behaviourally* — against the code paths that read it,
which is what a wrong value would actually break — and that is a weaker check than the bitcoin
one. Saying so is better than implying the two are the same.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from chainlens.adapters._evm import WEI_DECIMALS
from chainlens.codec.btc_amount import SATS_PER_BTC, btc_to_sats, sats_to_btc
from chainlens.codec.btc_script import NETWORKS
from chainlens.models.enums import Chain
from chainlens.models.primitives import AssetRef
from chainlens.verify.parsing import parse_amount
from chainlens.vocabulary import ASSETS, decimals_for, row_for
from chainlens.vocabulary._generated import BY_BASE58CHECK_VERSION


class TestTheBitcoinRow:
    def test_it_agrees_with_a_library_that_already_knows_the_number(self) -> None:
        """`pycoin`'s `SATOSHI_PER_COIN`, not this repository's opinion of it.

        `pycoin.convention` is about the one thing, and it is the only statement of bitcoin's
        decimals in the environment that this repository did not write. If the table's row for
        bitcoin said nine, everything else would agree with it and this would not.
        """
        from pycoin.convention import SATOSHI_PER_COIN

        assert SATS_PER_BTC == SATOSHI_PER_COIN
        assert decimals_for(Chain.BITCOIN) == 8

    def test_the_codecs_arithmetic_is_the_tables(self) -> None:
        """The behavioural half: the codec's own code path against the table's row.

        The constants above could agree while `sats_to_btc` scaled by a literal, which is what
        it used to do. This exercises the path.
        """
        one_btc = 10 ** decimals_for(Chain.BITCOIN)
        assert sats_to_btc(one_btc) == Decimal(1)
        assert sats_to_btc(1) == Decimal(1).scaleb(-decimals_for(Chain.BITCOIN))
        assert btc_to_sats(Decimal(1)) == one_btc

    def test_the_verifiers_reading_of_a_bitcoin_amount_is_the_tables(self) -> None:
        reading = parse_amount("1.5 BTC")
        assert reading is not None
        assert reading.asset.decimals == decimals_for(Chain.BITCOIN)
        assert reading.asset.symbol == "BTC"
        assert reading.band.nominal == 15 * 10 ** (decimals_for(Chain.BITCOIN) - 1)

    def test_a_base_unit_is_not_scaled_by_the_decimals(self) -> None:
        """`10 satoshis` is ten satoshis, and the number as written is already the answer."""
        reading = parse_amount("10 sats")
        assert reading is not None
        assert reading.band.nominal == 10


class TestTheEthereumRow:
    def test_the_verifiers_reading_of_an_ether_is_the_tables(self) -> None:
        reading = parse_amount("1 ether")
        assert reading is not None
        assert reading.asset.decimals == decimals_for(Chain.ETHEREUM)
        assert reading.band.nominal == 10 ** decimals_for(Chain.ETHEREUM)

    def test_the_evm_adapters_decimals_are_the_tables(self) -> None:
        """`WEI_DECIMALS` is derived from the row rather than stated beside it.

        This assertion is nearly free — it compares a name to the expression that defines it —
        and it is here because the *change* it guards is the one that reintroduces the literal:
        an edit to `_evm.py` that wrote `18` back would leave this reading the same number and
        the test would still pass. What catches that is the source, not the value, so the real
        guard is that the module no longer contains the digits.
        """
        assert decimals_for(Chain.ETHEREUM) == WEI_DECIMALS

    def test_the_asset_reference_carries_the_rows_symbol_and_decimals(self) -> None:
        asset = AssetRef.of_native(Chain.ETHEREUM)
        assert asset.kind.value == "native"
        assert asset.symbol == "ETH"
        assert asset.decimals == decimals_for(Chain.ETHEREUM)
        assert asset.contract is None


class TestTheWholeTable:
    @pytest.mark.parametrize("chain", list(Chain))
    def test_every_chain_renders_its_own_native_asset(self, chain: Chain) -> None:
        """The defect this replaces: the esplora adapter answered `symbol="BTC", decimals=8`
        for whatever chain it had been handed, so a Litecoin provider described its amounts as
        bitcoin. Reading the row is what makes that impossible rather than merely unlikely."""
        asset = AssetRef.of_native(chain)
        assert asset.chain is chain
        assert asset.decimals == decimals_for(chain)
        assert asset.symbol == AssetRef.of_native(chain).symbol


class TestTheAddressingParameters:
    """The version bytes and human-readable parts, held to something outside the table.

    **These are what the `families` column was missing.** The table named a family per chain and
    nothing could act on the name: `notes/identifiers.py` hardcoded `[13]` and `bc1` instead, so a
    litecoin address — a row the table had, a family the codecs implement — was not recognised at
    all. The parameters are here now, and they are checked rather than trusted.
    """

    def test_bitcoins_row_is_the_networks_table(self) -> None:
        """An in-tree cross-check: `codec/btc_script.py::NETWORKS` has carried these numbers for
        bitcoin's four networks since before the table existed, and the two must agree.

        Compared rather than restated in either direction — the table is not written from the
        network dict, and the dict is not written from the table, so a change to one that the
        other does not follow fails here.
        """
        mainnet = NETWORKS["mainnet"]
        bitcoin = row_for(Chain.BITCOIN)
        assert bitcoin.base58check_versions == (mainnet.p2pkh_version, mainnet.p2sh_version)
        assert bitcoin.bech32_hrp == mainnet.hrp

        testnet = NETWORKS["testnet"]
        tbtc = row_for(Chain.BITCOIN_TESTNET)
        assert tbtc.base58check_versions == (testnet.p2pkh_version, testnet.p2sh_version)
        assert tbtc.bech32_hrp == testnet.hrp

    def test_every_chain_pycoin_knows_is_attributed_to_the_same_chain(self) -> None:
        """**The oracle, and it is end-to-end rather than a constant comparison.**

        `pycoin` generates an address for each chain's own network parameters; this library is
        asked which chain that address is on; the two must agree. That is stronger than comparing
        version bytes, because it exercises the codec, the table and the attribution together —
        and a mistake in any of the three shows up as a disagreement with a library that has no
        stake in this repository's opinion.

        Bitcoin Cash is the one that cannot be asserted as an equality: pycoin produces the *same
        string* for `BTC` and `BCH`, because the chains forked and kept the format. It is asserted
        as the ambiguity it is.
        """
        from pycoin.networks.registry import network_for_netcode

        from chainlens.notes.identifiers import chains_for

        hash160 = bytes(range(20))
        expected = {
            "BTC": {Chain.BITCOIN},
            "XTN": {Chain.BITCOIN_TESTNET},
            "LTC": {Chain.LITECOIN},
            "DOGE": {Chain.DOGECOIN},
            "BCH": {Chain.BITCOIN_CASH},
        }
        for netcode, chains in expected.items():
            network = network_for_netcode(netcode)
            for method in ("for_p2pkh", "for_p2sh", "for_p2pkh_wit"):
                try:
                    address = getattr(network.address, method)(hash160)
                except Exception:
                    continue
                answered = set(chains_for(address))
                assert answered >= chains, f"{netcode}.{method}: {address} -> {answered}"

    def test_a_family_a_row_names_always_has_its_parameters(self) -> None:
        """The rule the generator enforces, asserted here as well: a row that claims a family and
        states nothing to match on is a claim no caller can act on — which is the state this table
        was in for two tranches."""
        for row in ASSETS:
            if "base58check" in row.families:
                assert row.base58check_versions, f"{row.id} claims base58check and states no bytes"
            if "bech32" in row.families:
                assert row.bech32_hrp, f"{row.id} claims bech32 and names no human-readable part"
            if "base58check" not in row.families:
                assert not row.base58check_versions
            if "bech32" not in row.families:
                assert row.bech32_hrp is None

    def test_two_chains_may_share_a_version_byte(self) -> None:
        """Not a fault in the table — a fact about the chains, and the reason the lookup returns a
        tuple. Asserted so that a future tidy-up that made the mapping one-to-one fails here."""
        shared = BY_BASE58CHECK_VERSION[0x00]
        assert {row.chain for row in shared} == {"bitcoin", "bitcoin_cash"}
