"""Investigation reporting.

Assembles analysis results into a document that can be audited: the
:class:`~chainlens.report.builder.InvestigationReport` model enforces a
methodology, a statement of limitations, and provenance for anything citing chain
data, and the renderers turn it into Markdown or standalone HTML.

:mod:`~chainlens.report.narrative` is the one part of this package that uses a model, and it is
bounded the same way the rest of the library bounds one: prose about a report may not contain a
figure the report does not, may not name a finding the report does not hold, and is discarded
paragraph by paragraph when it tries. The report is the artifact; the narrative is a view of it.
"""

from __future__ import annotations

from chainlens.report.builder import (
    STANDARD_LIMITATIONS,
    STANDARD_METHODOLOGY,
    FlowRow,
    InvestigationReport,
    ReportBuilder,
)
from chainlens.report.narrative import (
    DraftNarrative,
    DraftParagraph,
    NarrativeReport,
    Narrator,
    numerals,
    report_numerals,
)
from chainlens.report.render import render_html, render_markdown, template_environment

__all__ = [
    "STANDARD_LIMITATIONS",
    "STANDARD_METHODOLOGY",
    "DraftNarrative",
    "DraftParagraph",
    "FlowRow",
    "InvestigationReport",
    "NarrativeReport",
    "Narrator",
    "ReportBuilder",
    "numerals",
    "render_html",
    "render_markdown",
    "report_numerals",
    "template_environment",
]
