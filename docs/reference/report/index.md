# `chainlens.report`

Investigation reporting.

Assembles analysis results into a document that can be audited: the
`chainlens.report.builder.InvestigationReport` model enforces a
methodology, a statement of limitations, and provenance for anything citing chain
data, and the renderers turn it into Markdown or standalone HTML.

`chainlens.report.narrative` is the one part of this package that uses a model, and it is
bounded the same way the rest of the library bounds one: prose about a report may not contain a
figure the report does not, may not name a finding the report does not hold, and is discarded
paragraph by paragraph when it tries. The report is the artifact; the narrative is a view of it.
