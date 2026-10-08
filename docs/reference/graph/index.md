# `chainlens.graph`

Graph algorithms and serialisation over a value-flow graph.

The data model lives in `chainlens.models.flows`; this package turns it into
an indexed digraph for algorithms (`chainlens.graph.build`,
`chainlens.graph.metrics`) and into text formats for handing to other tools
(`chainlens.graph.export`).
