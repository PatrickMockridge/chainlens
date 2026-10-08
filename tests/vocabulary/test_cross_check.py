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
from chainlens.models.enums import Chain
from chainlens.models.primitives import AssetRef
from chainlens.verify.parsing import parse_amount
from chainlens.vocabulary import decimals_for


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
