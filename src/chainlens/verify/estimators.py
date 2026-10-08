"""The estimator that ships, and the one assumption it rests on.

A likelihood ratio needs a coincidence probability ``p`` — "how often does something that looks
like this happen anyway?" — and answering that needs a *sample* of transfers to count over. This
module draws that sample from what a provider can actually reach, and states plainly what the
sample is.

**The sample is the sender's own other movements, and that is a choice with a name.** The engine
reports it as ``NullModel.WITHIN_SENDER``: the alternative proposition being priced is "one of the
sender's *other* transfers coincidentally looks like the asserted payment". The competing
``POPULATION`` model — "a transfer of this shape is common network-wide" — needs a sample no
free provider can draw, and is refused here with its own reason rather than approximated from
something else. That refusal is the honest form of a real limitation: a network-wide rate would
be a different, and better, number, and this estimator cannot produce it.

Three further things are worth stating rather than discovering:

* **the sample is bounded.** Providers are read newest-first and a scan has a ceiling, so a busy
  address gives the *recent* history. When the ceiling bites, the estimate's ``population`` says
  so in words — "the sender's most recent N movements outside the window" — and the derivation
  renders that string verbatim, so a bounded sample cannot pass for an exhaustive one.
* **the window is the claim's, and it is the complement that is counted.** The claim's window is
  where the asserted transfer should be; the movements *inside* it are the opportunities ``k``,
  which the checker counts. A rate drawn from those would be circular, so the sample is what falls
  outside.
* **the sample is one asset's.** Base-unit amounts are only comparable within an asset, so the
  movements counted are the claim's asset and no other. On Bitcoin this is invisible — there is one
  asset — and on an account chain where an address moves ERC-20s it is the difference between a
  rate about this asset and a rate about a mixture.
* **nothing here decides anything.** The estimator returns a rate and the null it was drawn
  under. Whether a ratio is reported at all, and what it means, is the engine's and the
  likelihood module's business.
"""

from __future__ import annotations

from chainlens.models.calculation import UnboundKind
from chainlens.models.primitives import AssetRef, Transfer
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.verify.claims import ClaimElements
from chainlens.verify.likelihood import (
    ComponentEstimate,
    EstimatorMethod,
    NullModel,
    wilson_interval,
)
from chainlens.verify.verdicts import CoincidenceEstimator, RateEstimate, Unpriced

__all__ = ["DEFAULT_SAMPLE_LIMIT", "WindowCoincidenceEstimator", "estimator_for"]

#: How many of an address's movements to read before giving up on the rest. Bounds the requests a
#: ratio costs, and the bound is *reported* rather than hidden — see the module docstring.
DEFAULT_SAMPLE_LIMIT = 2_000


class WindowCoincidenceEstimator:
    """Prices a coincidence from the sender's own movements, as far back as a scan can reach.

    Args:
        null_model: which coincidence mechanism to price. Only ``WITHIN_SENDER`` can be drawn
            from one address's history; anything else is refused with its reason.
        sample_limit: how many movements to read before stopping. A sample that hits this is
            described as bounded rather than presented as the whole history.
    """

    def __init__(
        self,
        *,
        null_model: NullModel = NullModel.WITHIN_SENDER,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> None:
        self._null_model = null_model
        self._sample_limit = sample_limit

    async def estimate(
        self, elements: ClaimElements, *, provider: Provider
    ) -> RateEstimate | Unpriced | None:
        if self._null_model is not NullModel.WITHIN_SENDER:
            return Unpriced(
                f"the {self._null_model.value} null model prices a coincidence against a sample "
                "wider than any one address's history, and no configured provider can draw one: "
                "estimating it needs a population-level transfer sample. The ratio is withheld "
                "rather than computed from a rate this estimator cannot measure",
                kind=UnboundKind.NO_METHOD,
            )
        if elements.window is None:
            return Unpriced(
                "the claim names no window, so there is no period whose outside could be sampled: "
                "a coincidence rate measured over the sender's whole history would include the "
                "very transfers the claim is about. Give the claim a window",
                kind=UnboundKind.NO_DATA,
            )
        if not provider.supports(Capability.WINDOW_TRANSFERS):
            return Unpriced(
                f"provider {provider.name!r} cannot list an address's movements, which is what a "
                "coincidence rate is counted over; configure one that can",
                kind=UnboundKind.NO_DATA,
            )

        movements = [
            movement
            async for movement in provider.get_window_transfers(
                elements.sender, limit=self._sample_limit + 1
            )
        ]
        bounded = len(movements) > self._sample_limit
        movements = movements[: self._sample_limit]

        # **The sample is filtered to the claim's asset.** On a single-asset chain this is a no-op,
        # and on a chain where an address moves several kinds of value it is the difference between
        # a rate about this asset and a rate about a mixture. `_coincides` compares base-unit
        # amounts, and base units are only comparable within one asset: a token whose decimals
        # differ from the claim's makes an amount that lands inside the band meaningless. Counting
        # such a movement as a coincidence would invent a rate — and, because a coincidence rate
        # only ever moves the ratio by its `p`, invent it in the direction of confidence.
        same_asset = [
            movement for movement in movements if _same_asset(movement.asset, elements.asset)
        ]

        # The claim's window holds the opportunities, not the sample: counting the asserted
        # transfer among the transfers that would have to be coincidences is circular.
        sample = [
            movement for movement in same_asset if not elements.window.contains(movement.timestamp)
        ]
        if not sample:
            return Unpriced(
                "the sender has no movements of this asset outside the window to draw a "
                "coincidence rate from, so there is nothing to compare the asserted transfer "
                "against",
                samples=0,
                kind=UnboundKind.NO_DATA,
            )

        successes = sum(1 for movement in sample if _coincides(movement, elements))
        lower, upper = wilson_interval(successes, len(sample))
        return RateEstimate(
            component=ComponentEstimate(
                value=successes / len(sample),
                successes=successes,
                trials=len(sample),
                ci_lower=lower,
                ci_upper=upper,
                method=EstimatorMethod.EMPIRICAL_JOINT,
                population=self._population(bounded=bounded, asset=elements.asset),
            ),
            null_model=self._null_model,
        )

    def _population(self, *, bounded: bool, asset: AssetRef) -> str:
        """What the rate was measured over, in the words a derivation renders.

        The asset is named because the rate is only about one: "the sender's movements" would
        describe a sample that included every token they touched, which is not what was counted.
        """
        # Phrased so it reads as English whether or not the asset carries a symbol: "movements of
        # BTC" and "movements of the native asset" both work, where "BTC movements" degenerates to
        # "native movements" when nothing named the asset.
        named = asset.symbol or f"the {asset.kind.value} asset"
        if bounded:
            return (
                f"the sender's most recent {self._sample_limit} movements of {named} outside the "
                "window, which is as far back as the scan reached and not the whole of their "
                "history"
            )
        return f"the sender's whole movement history in {named} outside the window"


def _same_asset(left: AssetRef, right: AssetRef) -> bool:
    """Whether two movements are of the same asset, on the same chain.

    Compares the contract as well as the kind: on an account chain "token" is a category, and two
    different ERC-20s are two different assets with their own decimals, so an amount of one says
    nothing about an amount of the other.
    """
    if left.chain is not right.chain or left.kind is not right.kind:
        return False
    if left.contract is None or right.contract is None:
        return left.contract is None and right.contract is None
    return left.contract.lower() == right.contract.lower()


def _coincides(movement: Transfer, elements: ClaimElements) -> bool:
    """Whether one of the sender's other movements looks like the asserted payment.

    The same test the checker applies to a candidate, applied to the *sample* instead: that is what
    makes the rate an estimate of the thing the ratio is about rather than of something adjacent to
    it. A claim naming no recipient is matched on the amount alone, exactly as the check matches it.
    """
    if elements.recipient is not None and movement.dst != elements.recipient:
        return False
    return elements.band is None or elements.band.contains(movement.amount)


def estimator_for(
    provider: Provider, *, null_model: NullModel = NullModel.WITHIN_SENDER
) -> CoincidenceEstimator | None:
    """An estimator when the provider can supply what one needs, and ``None`` when it cannot.

    ``None`` rather than an estimator that always refuses: the engine's "no coincidence estimator
    is configured" reason is the honest one when there is nothing to configure, and a refusal
    dressed as a data problem would send a reader looking for data that would not help.
    """
    if not provider.supports(Capability.WINDOW_TRANSFERS):
        return None
    return WindowCoincidenceEstimator(null_model=null_model)
