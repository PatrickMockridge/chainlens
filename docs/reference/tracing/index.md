# `chainlens.tracing`

Value-flow tracing.

Walks value from a seed address, producing a bounded
`chainlens.models.flows.FlowGraph`. Composes with clustering: supply a
`chainlens.analysis.clustering.Clusterer` and the graph is an entity graph
rather than an address graph.
