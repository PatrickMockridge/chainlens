"""Render a report to Markdown or to standalone HTML.

Two templates over one model, rather than Markdown converted to HTML. That keeps
the report layer free of a Markdown dependency, and it means each format is written
to be read in its own medium instead of being a transcription of the other.

Templates ship as package data, so an application can override them without
forking: pass ``template_dir`` and the environment loads from there instead. The
renderer is **strict** — an undefined name in a template is an error, not a silently
blank section, because a report that quietly drops a field is worse than one that
refuses to render.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, PackageLoader, StrictUndefined

from chainlens.graph.export import to_mermaid
from chainlens.report.builder import InvestigationReport

__all__ = ["render_html", "render_markdown", "template_environment"]

_TEMPLATE_PACKAGE = "chainlens.report"
_TEMPLATE_DIR = "templates"

_MARKDOWN_TEMPLATE = "report.md.j2"
_HTML_TEMPLATE = "report.html.j2"


def template_environment(
    *, template_dir: str | Path | None = None, autoescape: bool = False
) -> Environment:
    """Build the Jinja environment used by both renderers.

    Args:
        template_dir: load templates from here instead of the package data. This is
            the supported way to restyle a report without forking the library.
        autoescape: escape interpolated values. On for HTML, off for Markdown,
            where escaping would corrupt the output.
    """
    loader = (
        FileSystemLoader(str(template_dir))
        if template_dir is not None
        else PackageLoader(_TEMPLATE_PACKAGE, _TEMPLATE_DIR)
    )
    environment = Environment(
        loader=loader,
        autoescape=autoescape,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters["mermaid"] = lambda graph: "" if graph is None else to_mermaid(graph)
    environment.filters["percent"] = lambda value: f"{float(value) * 100:.0f}%"
    return environment


def _context(report: InvestigationReport) -> dict[str, object]:
    return {
        "report": report,
        "flows": report.flow_rows(),
        "provenance_lines": report.provenance_keys(),
        "window_start": report.activity_window[0],
        "window_end": report.activity_window[1],
    }


def render_markdown(report: InvestigationReport, *, template_dir: str | Path | None = None) -> str:
    """Render the Markdown form, for version control and diffs."""
    environment = template_environment(template_dir=template_dir)
    template = environment.get_template(_MARKDOWN_TEMPLATE)
    return template.render(**_context(report))


def render_html(report: InvestigationReport, *, template_dir: str | Path | None = None) -> str:
    """Render a standalone HTML document, with inline styles and no build step.

    The flow diagram is embedded as Mermaid source. Rendering it needs the Mermaid
    script, which the template references from a CDN, so the diagram requires
    network access (or a local copy) to appear -- the flow *table* beside it is
    plain HTML and always renders.
    """
    environment = template_environment(template_dir=template_dir, autoescape=True)
    template = environment.get_template(_HTML_TEMPLATE)
    return template.render(**_context(report))
