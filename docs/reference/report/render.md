# `chainlens.report.render`

Render a report to Markdown or to standalone HTML.

Two templates over one model, rather than Markdown converted to HTML. That keeps
the report layer free of a Markdown dependency, and it means each format is written
to be read in its own medium instead of being a transcription of the other.

Templates ship as package data, so an application can override them without
forking: pass ``template_dir`` and the environment loads from there instead. The
renderer is **strict** — an undefined name in a template is an error, not a silently
blank section, because a report that quietly drops a field is worse than one that
refuses to render.

## `render_html`

```python
render_html(report: InvestigationReport, *, template_dir: str | Path | None = None) -> str
```

Render a standalone HTML document, with inline styles and no build step.

The flow diagram is embedded as Mermaid source. Rendering it needs the Mermaid
script, which the template references from a CDN, so the diagram requires
network access (or a local copy) to appear -- the flow *table* beside it is
plain HTML and always renders.

## `render_markdown`

```python
render_markdown(report: InvestigationReport, *, template_dir: str | Path | None = None) -> str
```

Render the Markdown form, for version control and diffs.

## `template_environment`

```python
template_environment(*, template_dir: str | Path | None = None, autoescape: bool = False) -> Environment
```

Build the Jinja environment used by both renderers.

**Parameters**

- `template_dir` `str | Path | None`, default `None` — load templates from here instead of the package data. This is the supported way to restyle a report without forking the library.
- `autoescape` `bool`, default `False` — escape interpolated values. On for HTML, off for Markdown, where escaping would corrupt the output.
