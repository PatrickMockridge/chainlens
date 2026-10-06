"""Assemble a defensible investigation report from analysis results.

The point of this module is not formatting. It is that **a report which cannot be
checked is not a report**, so two sections are mandatory and structurally
enforced rather than optional extras a caller might forget:

* **Methodology** — what was done, with which tool, under which limits.
* **Provenance** — where every fact came from, deduplicated and listed.

A report that cites chain data while recording no provenance fails to construct.
That is a `ValueError` at build time rather than a quiet omission in a PDF, because
the failure mode it prevents is a document that looks authoritative and cannot be
audited.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from pydantic import Field, model_validator

from chainlens.analysis.clustering import ClusterResult, Refusal
from chainlens.graph.export import amount_label
from chainlens.graph.metrics import GraphSummary
from chainlens.models.base import LensModel, Provenance, utcnow
from chainlens.models.entities import Entity, Label
from chainlens.models.enums import Chain
from chainlens.models.flows import FlowGraph, ValueFlow

__all__ = [
    "STANDARD_LIMITATIONS",
    "STANDARD_METHODOLOGY",
    "FlowRow",
    "InvestigationReport",
    "ReportBuilder",
]

STANDARD_METHODOLOGY = """\
Chain data was retrieved from the providers listed under Data provenance and
normalized by chainlens. Addresses were grouped into entities by the clustering
heuristics named against each entity, each of which records its own confidence and
the evidence that fired. Value flows were traced from the seed under the budget
recorded in Summary; every edge lists the transaction ids that support it.
"""

STANDARD_LIMITATIONS = """\
Clusters and flows are hypotheses, not facts. On-chain heuristics produce false
positives, and the common-input-ownership rule in particular is unreliable on
CoinJoin transactions, which this library detects and skips rather than scores.

Amounts apportioned across several senders are an inference: a UTXO transaction
does not record which input paid which output, so those edges carry a confidence
below 1.0 and their txids are listed so the split can be re-derived.

A trace that reports truncation stopped early. It is not a statement that nothing
further exists.

Nothing here identifies a person. Addresses are grouped; attributing a group to a
named actor requires an external label source, which will be recorded as such if
one was used.
"""


class FlowRow(LensModel):
    """One value movement, flattened for tabular rendering.

    ``txids`` is carried into the table rather than summarised away: an amount a
    reader cannot trace back to a transaction is an assertion, not evidence.
    """

    src: str
    dst: str
    amount: int = Field(ge=0)
    amount_label: str
    asset_kind: str
    hops: int = Field(ge=0)
    n_transfers: int = Field(ge=1)
    txids: tuple[str, ...] = ()
    #: 1.0 or 0.5 and nothing else, so a renderer can say "apportioned" rather than showing a
    #: reader a number that looks measured. Derived on :class:`~chainlens.models.flows.ValueFlow`,
    #: and carried here because a table has a column for it.
    confidence: float = Field(ge=0.0, le=1.0)
    #: The same fact as a flag, which is what it always was.
    apportioned: bool = False
    is_change: bool = False


class InvestigationReport(LensModel):
    """A complete, renderable report.

    Attributes:
        title: what this report is about.
        chain: the chain analysed.
        seed: the address the trace started from.
        created_at: when it was assembled.
        graph: the traced value-flow graph, if a trace was run.
        entities: clusters found, with their evidence.
        observations: labels produced by heuristics rather than merges.
        summary: structural metrics over the graph.
        refusals: merges a declared non-equivalence forbade.
        warnings: anything that truncated or degraded the analysis.
        provenance: every source consulted, deduplicated.
        redistributable: whether the sources permit redistributing this content.
        methodology: how the analysis was performed. Must not be empty.
        limitations: what the output does and does not support. Must not be empty.
    """

    title: str
    chain: Chain
    seed: str
    created_at: datetime

    graph: FlowGraph | None = None
    entities: tuple[Entity, ...] = ()
    observations: tuple[Label, ...] = ()
    summary: GraphSummary | None = None
    refusals: tuple[Refusal, ...] = ()
    warnings: tuple[str, ...] = ()

    provenance: tuple[Provenance, ...] = ()
    redistributable: bool = False

    methodology: str = STANDARD_METHODOLOGY
    limitations: str = STANDARD_LIMITATIONS

    @model_validator(mode="after")
    def _require_a_defensible_document(self) -> InvestigationReport:
        if not self.methodology.strip():
            raise ValueError(
                "a report must state its methodology; a finding without one cannot be evaluated"
            )
        if not self.limitations.strip():
            raise ValueError(
                "a report must state its limitations; a hypothesis presented without them "
                "reads as a fact"
            )
        cites_chain_data = bool(self.entities) or (
            self.graph is not None and not self.graph.is_empty
        )
        if cites_chain_data and not self.provenance:
            raise ValueError(
                "a report citing chain data must record where it came from; without "
                "provenance the output cannot be audited"
            )
        return self

    @property
    def truncated(self) -> bool:
        """Whether the underlying trace stopped early."""
        return self.graph is not None and self.graph.truncated

    @property
    def flows(self) -> tuple[ValueFlow, ...]:
        """Edges, largest first, then by key so the order is stable."""
        if self.graph is None:
            return ()
        return tuple(sorted(self.graph.edges, key=lambda edge: (-edge.amount, edge.edge_key)))

    def flow_rows(self) -> tuple[FlowRow, ...]:
        """Flattened edges, ready for a table."""
        return tuple(
            FlowRow(
                src=str(edge.src),
                dst=str(edge.dst),
                amount=edge.amount,
                amount_label=amount_label(edge),
                asset_kind=str(edge.asset.kind),
                hops=edge.hops,
                n_transfers=edge.n_transfers,
                txids=edge.txids,
                confidence=edge.confidence,
                apportioned=edge.apportioned,
                is_change=edge.is_change,
            )
            for edge in self.flows
        )

    def apportioned_flow_count(self) -> int:
        """How many edges rest on an apportioned rather than recorded split."""
        return sum(1 for edge in self.flows if edge.apportioned)

    @property
    def activity_window(self) -> tuple[datetime | None, datetime | None]:
        """Earliest and latest timestamps seen on any edge, if the provider supplied them.

        ``None`` for both when no edge carried a timestamp, which is common on
        providers that omit block times. Reported as unknown rather than as the
        report's own generation time.
        """
        stamps = [
            stamp
            for edge in self.flows
            for stamp in (edge.first_seen, edge.last_seen)
            if stamp is not None
        ]
        return (min(stamps), max(stamps)) if stamps else (None, None)

    def labelled_entities(self) -> tuple[Entity, ...]:
        """Entities carrying at least one label -- the ones an analyst cares about."""
        return tuple(entity for entity in self.entities if entity.is_labeled)

    def all_txids(self) -> tuple[str, ...]:
        """Every transaction id cited anywhere in the report, sorted and deduplicated."""
        return tuple(sorted({txid for edge in self.flows for txid in edge.txids}))

    def provenance_keys(self) -> tuple[str, ...]:
        """Each source rendered as a short line for the provenance table."""
        return tuple(
            f"{item.provider}"
            + (f" {item.endpoint}" if item.endpoint else "")
            + (f" (request {item.request_id})" if item.request_id else "")
            + f" — fetched {item.fetched_at:%Y-%m-%d %H:%M:%SZ}"
            for item in self.provenance
        )


class ReportBuilder:
    """Collects analysis results and assembles a report.

    Args:
        title: overrides the derived title.
        methodology: overrides the standard text. Passing an empty string is
            rejected at build time -- the field exists so a caller can be *more*
            specific, not to allow omitting it.
        limitations: as above.
        redistributable: whether the sources permit redistributing this content.
            Defaults to ``False``, the cautious answer, because assuming otherwise
            is the mistake with legal consequences.
    """

    def __init__(
        self,
        *,
        title: str | None = None,
        methodology: str | None = None,
        limitations: str | None = None,
        redistributable: bool = False,
    ) -> None:
        self._title = title
        self._methodology = methodology
        self._limitations = limitations
        self._redistributable = redistributable

    def build(
        self,
        *,
        chain: Chain,
        seed: str,
        graph: FlowGraph | None = None,
        cluster_result: ClusterResult | None = None,
        summary: GraphSummary | None = None,
        entities: Sequence[Entity] = (),
        observations: Iterable[Label] = (),
        refusals: Iterable[Refusal] = (),
        warnings: Iterable[str] = (),
    ) -> InvestigationReport:
        """Assemble a report, collecting provenance from everything supplied."""
        collected_entities = tuple(entities)
        collected_observations = list(observations)
        collected_refusals = list(refusals)
        collected_warnings = list(warnings)

        if cluster_result is not None:
            collected_entities = collected_entities or cluster_result.entities
            collected_observations.extend(cluster_result.observations)
            collected_refusals.extend(cluster_result.refusals)
            collected_warnings.extend(cluster_result.warnings)

        provenance = _collect_provenance(
            graph=graph,
            entities=collected_entities,
            observations=collected_observations,
        )

        if graph is not None:
            collected_warnings.extend(graph.warnings)

        return InvestigationReport(
            title=self._title or f"Investigation of {seed}",
            chain=chain,
            seed=seed,
            created_at=utcnow(),
            graph=graph,
            entities=collected_entities,
            observations=tuple(collected_observations),
            summary=summary,
            refusals=tuple(collected_refusals),
            warnings=tuple(dict.fromkeys(collected_warnings)),
            provenance=provenance,
            redistributable=self._redistributable,
            # `is None`, not `or`: an explicitly empty string must reach the validator
            # and be rejected, rather than being quietly replaced by the default. The
            # field exists so a caller can be more specific, never to omit the section.
            methodology=STANDARD_METHODOLOGY if self._methodology is None else self._methodology,
            limitations=STANDARD_LIMITATIONS if self._limitations is None else self._limitations,
        )


def _collect_provenance(
    *,
    graph: FlowGraph | None,
    entities: Sequence[Entity],
    observations: Sequence[Label],
) -> tuple[Provenance, ...]:
    """Every distinct source consulted, in first-seen order.

    Deduplicated on the fields that identify a *fetch* rather than a fact, so one
    endpoint polled twenty times appears once.
    """
    seen: dict[tuple[object, ...], Provenance] = {}

    def remember(item: Provenance | None) -> None:
        if item is None:
            return
        key = (item.provider, item.endpoint, item.request_id, item.fetched_at, item.cached)
        seen.setdefault(key, item)

    if graph is not None:
        for edge in graph.edges:
            remember(edge.provenance)
    for entity in entities:
        remember(entity.provenance)

    return tuple(seen.values())
