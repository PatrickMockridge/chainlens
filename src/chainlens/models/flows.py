"""Value-flow graph vocabulary.

A :class:`ValueFlow` endpoint is a :data:`NodeRef`, which is *either* a raw
address or an entity (a cluster of addresses believed to share a controller).
That choice is what lets tracing compose with clustering: once two addresses are
merged into one entity, the graph can say "this entity sent 3.4 BTC to that
entity" instead of pretending they are still separate actors.

``NodeRef`` is a discriminated union on the ``kind`` literal, so pydantic round
trips it without a caller having to guess which arm a dict represents.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import Chain, FlowDirection, FlowVia
from chainlens.models.primitives import AssetRef, _to_decimal

__all__ = ["AddressRef", "EntityRef", "NodeRef", "ValueFlow"]


class AddressRef(LensModel):
    """A graph node that is a single address."""

    kind: Literal["address"] = "address"
    chain: Chain
    address: str

    @property
    def node_key(self) -> str:
        """Stable identity string, suitable as a dict key across runs."""
        return f"address:{self.chain}:{self.address}"

    def __str__(self) -> str:
        return self.address


class EntityRef(LensModel):
    """A graph node that is a cluster of addresses.

    ``label`` is a display convenience only; the identity is ``entity_id``.
    """

    kind: Literal["entity"] = "entity"
    chain: Chain
    entity_id: str
    label: str | None = None

    @property
    def node_key(self) -> str:
        return f"entity:{self.chain}:{self.entity_id}"

    def __str__(self) -> str:
        return self.label or self.entity_id


NodeRef = Annotated[AddressRef | EntityRef, Field(discriminator="kind")]


class ValueFlow(LensModel):
    """An aggregated movement of value between two graph nodes.

    Individual transfers between the same pair of nodes (possibly across many
    transactions) are folded into one edge, with ``n_transfers`` and ``txids``
    recording what was combined. ``path`` records the ordered node keys from the
    trace root to this edge, which is what makes path-based reporting possible
    without re-running the traversal.
    """

    chain: Chain
    src: NodeRef
    dst: NodeRef
    asset: AssetRef

    amount: int
    n_transfers: int = 1
    txids: tuple[str, ...] = ()

    first_seen: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None

    hops: int = 0
    direction: FlowDirection = FlowDirection.OUT
    via: FlowVia = FlowVia.NATIVE

    path: tuple[str, ...] = ()
    is_change: bool = False

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    heuristics: tuple[str, ...] = ()

    provenance: Provenance | None = None

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly."""
        return _to_decimal(self.amount, self.asset)

    @property
    def edge_key(self) -> tuple[str, str, str]:
        """Identity of this edge: ``(src, dst, asset-ish)``."""
        return (self.src.node_key, self.dst.node_key, str(self.asset.kind))

    @property
    def is_self_loop(self) -> bool:
        """Whether both endpoints are the same node (a change output, typically)."""
        return self.src.node_key == self.dst.node_key
