"""Investigation reporting.

Assembles analysis results into a document that can be audited: the
:class:`~chainlens.report.builder.InvestigationReport` model enforces a
methodology, a statement of limitations, and provenance for anything citing chain
data, and the renderers turn it into Markdown or standalone HTML.
"""

from __future__ import annotations

from chainlens.report.builder import (
    STANDARD_LIMITATIONS,
    STANDARD_METHODOLOGY,
    FlowRow,
    InvestigationReport,
    ReportBuilder,
)
from chainlens.report.render import render_html, render_markdown, template_environment

__all__ = [
    "STANDARD_LIMITATIONS",
    "STANDARD_METHODOLOGY",
    "FlowRow",
    "InvestigationReport",
    "ReportBuilder",
    "render_html",
    "render_markdown",
    "template_environment",
]
