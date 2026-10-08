"""The amount that knows what it is, and the chain/asset rule four models share.

Two things are tested here and they are the two halves of one idea. The **dimension** is
``(chain, asset)``: a value that pairs a chain with an asset on another chain is refused, in
every model that pairs them. The **tag** is how the number was arrived at: a recorded figure and
an apportioned share are different kinds even when their dimension is the same.

The refusal is tested on all four models rather than on `Amount` alone, because the rule is one
fact — `require_asset_on_chain` — and a test of one model would pass while another kept the hole
open. Before this tranche, all four were open and nothing was constructing a bad pair, which is
exactly why it took reading the type to find them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from chainlens.models.enums import (
    AMOUNT_STATUS_SPELLINGS,
    AmountTag,
    AssetKind,
    Chain,
    FlowDirection,
)
from chainlens.models.flows import AddressRef, ValueFlow
from chainlens.models.ledger import AmountStatus, LedgerEdge, LedgerEdgeRole
from chainlens.models.primitives import Amount, AssetRef, Balance, Transfer

DIMENSION_ERROR = "not on its own chain"
BTC = AssetRef.of_native(Chain.BITCOIN)
ETH = AssetRef.of_native(Chain.ETHEREUM)
USDC = AssetRef(
    chain=Chain.ETHEREUM, kind=AssetKind.ERC20, symbol="USDC", decimals=6, contract="0xusdc"
)


def _transfer(**overrides: object) -> Transfer:
    fields: dict[str, object] = {
        "chain": Chain.BITCOIN,
        "asset": BTC,
        "amount": 100,
        "txid": "t",
        "src": "a",
        "dst": "b",
    }
    fields.update(overrides)
    return Transfer(**fields)  # type: ignore[arg-type]


class TestTheDimension:
    def test_an_amount_of_a_chains_own_coin_is_fine(self) -> None:
        amount = Amount(chain=Chain.BITCOIN, asset=BTC, base_units=1)
        assert amount.chain is Chain.BITCOIN
        assert amount.asset.symbol == "BTC"
        assert amount.tag is AmountTag.RECORDED

    def test_an_asset_on_another_chain_is_refused(self) -> None:
        """The hole this tranche closes, stated as the sentence a reader needs.

        A bitcoin holding an ethereum is not a large number or a small one; it is a value with
        no meaning, and a type that permits it makes the mistake available to every reader
        downstream who does not happen to know which field to trust.
        """
        with pytest.raises(ValueError, match=DIMENSION_ERROR):
            Amount(chain=Chain.BITCOIN, asset=ETH, base_units=1)

    def test_a_token_on_its_own_chain_is_fine(self) -> None:
        """The identity of a token is its contract on a chain, which is why `asset` is an
        `AssetRef` and not the vocabulary table's row id — there is no row for a token."""
        amount = Amount(chain=Chain.ETHEREUM, asset=USDC, base_units=1_000_000)
        assert amount.asset.contract == "0xusdc"
        assert amount.amount_to_decimal() == Decimal(1)

    @pytest.mark.parametrize("model", ["Transfer", "Balance", "ValueFlow"])
    def test_every_model_that_pairs_a_chain_with_an_asset_refuses_a_mismatch(
        self, model: str
    ) -> None:
        """Four models, one rule. Each is exercised because each was separately open."""
        with pytest.raises(ValueError, match=DIMENSION_ERROR):
            _pair(model, chain=Chain.BITCOIN, asset=ETH)

    @pytest.mark.parametrize("model", ["Transfer", "Balance", "ValueFlow"])
    def test_every_model_still_accepts_a_matching_pair(self, model: str) -> None:
        built = _pair(model, chain=Chain.ETHEREUM, asset=USDC)
        assert built.asset is USDC


def _pair(model: str, *, chain: Chain, asset: AssetRef) -> Transfer | Balance | ValueFlow:
    """One construction of each model that pairs a chain with an asset."""
    if model == "Transfer":
        return Transfer(chain=chain, asset=asset, amount=1, txid="t")
    if model == "Balance":
        return Balance(chain=chain, address="a", asset=asset, amount=1)
    node = AddressRef(chain=chain, address="a")
    return ValueFlow(
        chain=chain,
        src=node,
        dst=node,
        asset=asset,
        amount=1,
        direction=FlowDirection.OUT,
    )


class TestTheTag:
    def test_a_recorded_transfer_becomes_a_recorded_amount(self) -> None:
        amount = Amount.of(_transfer())
        assert amount.tag is AmountTag.RECORDED
        assert amount.base_units == 100

    def test_an_ambiguous_transfer_becomes_an_apportioned_amount(self) -> None:
        """`ambiguous` already says the sender attribution is this library's convention rather
        than something the chain recorded. The tag is that fact with a name, so the mapping is
        the point of the adapter rather than a default."""
        amount = Amount.of(_transfer(ambiguous=True))
        assert amount.tag is AmountTag.APPORTIONED

    def test_the_tag_can_be_overridden_out_loud(self) -> None:
        amount = Amount.of(_transfer(ambiguous=True), tag=AmountTag.RECORDED)
        assert amount.tag is AmountTag.RECORDED

    def test_a_balance_is_recorded(self) -> None:
        balance = Balance(chain=Chain.BITCOIN, address="a", asset=BTC, amount=5)
        assert Amount.of_balance(balance).tag is AmountTag.RECORDED
        assert balance.to_amount().tag is AmountTag.RECORDED

    def test_re_tagging_is_a_method_rather_than_a_mutable_field(self) -> None:
        amount = Amount.of(_transfer(ambiguous=True))
        accepted = amount.with_tag(AmountTag.RECORDED)
        assert accepted.tag is AmountTag.RECORDED
        assert amount.tag is AmountTag.APPORTIONED, "the original is unchanged"

    def test_a_transfer_converts_through_its_own_accessor(self) -> None:
        assert _transfer(ambiguous=True).to_amount().tag is AmountTag.APPORTIONED


class TestTheSum:
    def test_two_amounts_of_one_dimension_add(self) -> None:
        total = Amount(chain=Chain.BITCOIN, asset=BTC, base_units=3) + Amount(
            chain=Chain.BITCOIN, asset=BTC, base_units=4
        )
        assert total.base_units == 7

    def test_two_dimensions_cannot_be_added(self) -> None:
        """The operation the layer exists to refuse. A sum across dimensions is not a large
        number, it is a meaningless one, and it carries no sign of having happened."""
        with pytest.raises(TypeError, match="different dimensions"):
            Amount(chain=Chain.BITCOIN, asset=BTC, base_units=1) + Amount(
                chain=Chain.ETHEREUM, asset=ETH, base_units=1
            )

    def test_a_token_and_its_chains_coin_are_two_dimensions(self) -> None:
        """Same chain, different asset — which is why the dimension is `(chain, asset)` and not
        just `chain`."""
        with pytest.raises(TypeError, match="different dimensions"):
            Amount(chain=Chain.ETHEREUM, asset=ETH, base_units=1) + Amount(
                chain=Chain.ETHEREUM, asset=USDC, base_units=1
            )

    def test_a_sum_inherits_its_weakest_term(self) -> None:
        """A total whose components include an inference is an inference. The tag is not a
        property of the largest term or the first one."""
        recorded = Amount(chain=Chain.BITCOIN, asset=BTC, base_units=1)
        apportioned = Amount(
            chain=Chain.BITCOIN, asset=BTC, base_units=1, tag=AmountTag.APPORTIONED
        )
        assert (recorded + apportioned).tag is AmountTag.APPORTIONED
        assert (apportioned + recorded).tag is AmountTag.APPORTIONED
        assert (recorded + recorded).tag is AmountTag.RECORDED


class TestRendering:
    def test_an_amount_renders_exactly_and_refuses_when_it_cannot(self) -> None:
        assert Amount(chain=Chain.ETHEREUM, asset=ETH, base_units=10**18).amount_to_decimal() == 1
        unknown = AssetRef(chain=Chain.ETHEREUM, kind=AssetKind.ERC20, contract="0x1")
        with pytest.raises(ValueError, match="decimals are unknown"):
            Amount(chain=Chain.ETHEREUM, asset=unknown, base_units=1).amount_to_decimal()


class TestTheLedgerViewsStatus:
    """**Two overlapping vocabularies, and neither is a subset of the other.**

    The ledger view has `missing` and cannot have `apportioned` — it does not estimate, so it has
    nothing to apportion. The flow view has `apportioned` and cannot have `missing` — an `Amount`
    always carries a figure. `recorded` is the one word they share.

    **This class used to assert a subset**, which was true only while `AmountTag` carried a
    `MISSING` member that nothing could set. Removing that member is what made the real relation
    visible, and the assertion here is the corrected one rather than a weakened one: what is
    asserted now is *more* than a subset — it is exactly the intersection.
    """

    def test_the_two_vocabularies_meet_in_one_word(self) -> None:
        tags = {member.value for member in AmountTag}
        statuses = {member.value for member in AmountStatus}
        assert tags & statuses == {"recorded"}
        assert tags - statuses == {"apportioned"}
        assert statuses - tags == {"missing"}

    def test_the_shared_word_is_written_down_once(self) -> None:
        """An enum that happened to agree with another on `"recorded"` would be a second place that
        string lived, and one of the two would change first."""
        assert {"recorded": AmountTag.RECORDED.value} == AMOUNT_STATUS_SPELLINGS
        assert AmountStatus.RECORDED.value == AMOUNT_STATUS_SPELLINGS["recorded"]

    def test_the_ledger_view_has_no_apportioned_member(self) -> None:
        """Not an omission. This view does not estimate, so a member for it would invite a
        value nothing sets — the failure the vocabulary table exists to prevent one layer up."""
        assert "APPORTIONED" not in AmountStatus.__members__

    def test_the_tag_has_no_missing_member_because_none_could_be_set(self) -> None:
        """The member that was there and was unreachable.

        `Amount.base_units` is required, so an amount whose figure nobody recorded cannot be an
        `Amount` at all — every construction site yields `RECORDED` or `APPORTIONED`. The absence
        of a number is the absence of an `Amount`, which is a stronger statement than a tag on one.
        """
        assert "MISSING" not in AmountTag.__members__
        with pytest.raises(ValidationError):
            Amount(
                chain=Chain.BITCOIN,
                asset=AssetRef.of_native(Chain.BITCOIN),
                base_units=None,  # type: ignore[arg-type]
            )

    def test_a_ledger_edge_refuses_a_mismatched_asset(self) -> None:
        """The fifth model pairing a chain with an asset, and the validator is the same one."""
        with pytest.raises(ValueError, match=DIMENSION_ERROR):
            LedgerEdge(
                key="k",
                src="a",
                dst="b",
                chain=Chain.BITCOIN,
                txid="t",
                role=LedgerEdgeRole.OUTPUT,
                asset=ETH,
            )

    def test_a_ledger_edge_without_an_asset_is_fine(self) -> None:
        """`asset` is optional here — a provider may not name it — so absence is not a
        mismatch."""
        edge = LedgerEdge(
            key="k", src="a", dst="b", chain=Chain.BITCOIN, txid="t", role=LedgerEdgeRole.OUTPUT
        )
        assert edge.asset is None
