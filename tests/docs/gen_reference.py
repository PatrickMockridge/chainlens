"""Render the API reference to markdown, from the docstrings themselves.

**Why this exists at all.** mdbook has no equivalent of ``mkdocstrings``: it renders markdown and
nothing else, and the API reference is the one part of this documentation that is generated rather
than written. The alternatives were to drop it or to run a second documentation toolchain
alongside mdbook, and both are worse than a generator.

**Why here rather than in a tools directory.** The staleness test has to import this, and pytest
puts a test file's own directory on ``sys.path`` -- so ``import gen_reference`` works with no path
arrangement, exactly as ``tests/ledger/test_contract.py`` imports ``fixtures`` from beside it. The
same reason that generator lives where it does.

**Why ``griffe``.** It is the parser ``mkdocstrings-python`` is built on, so the docstrings are
read the way they have always been read -- Google style, parsed into sections, with signatures
rendered from the annotations. Nothing here parses a docstring by hand, which means a docstring
written in the house style renders without anybody teaching this file about it.

**What it costs.** The pages are plainer than mkdocstrings produced: no cross-reference resolution
between pages, and no anchors generated from the object path. What is kept is the thing that
matters -- the reference cannot go stale, because ``make docs-reference`` regenerates it and
``tests/docs/test_reference.py`` fails on a diff.

Run it the way ``make docs-reference`` does::

    uv run python tests/docs/gen_reference.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeGuard

import griffe

__all__ = ["render_all", "write_all"]

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
DOCS = ROOT / "docs"
SUMMARY = DOCS / "SUMMARY.md"

#: The markers the reference block in ``SUMMARY.md`` sits between. Everything outside them is the
#: guide, which is written by hand and never touched by this file.
BEGIN = "<!-- GENERATED:REFERENCE -->"
END = "<!-- END GENERATED:REFERENCE -->"

#: What a heading level is worth. A module is `#`, its members `##`, and a class's own members
#: `###`; the generator never goes deeper, because a reader scrolling a reference page is looking
#: for a name rather than for a hierarchy.
_MAX_DEPTH = 3


def _load() -> griffe.Module:
    """The package, read statically.

    Static rather than by import, for the reason the mkdocs config gave: importing the package
    triggers provider plugin discovery as a side effect, and a docs build should not be able to
    load a third-party adapter or read the environment.
    """
    loaded = griffe.load("chainlens", search_paths=[str(SOURCE_ROOT)])
    if not isinstance(loaded, griffe.Module):
        # `load` returns whatever the name resolved to. If `chainlens` stopped being a package
        # there would be no tree to render, and saying so beats a traceback from the walk below.
        raise TypeError(f"chainlens resolved to {type(loaded).__name__}, not a module")
    return loaded


def _modules(source_root: Path = SOURCE_ROOT) -> list[tuple[tuple[str, ...], str]]:
    """Every public module, as its dotted parts and the reference page it is rendered to.

    The mapping is the one the mkdocs generator used: a module's path under ``src/`` becomes the
    same path under ``docs/reference/``, an ``__init__`` becomes that directory's ``index.md``,
    and a module whose name starts with an underscore is private and is not part of the public
    API.
    """
    found: list[tuple[tuple[str, ...], str]] = []
    for path in sorted(source_root.rglob("*.py")):
        parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        # `__init__` is checked **before** the private-name rule, and the order is load-bearing:
        # an `elif` the other way round filters out every package's `__init__.py` as a private
        # module, which silently drops all thirteen section index pages.
        package = parts[-1] == "__init__"
        if package:
            parts = parts[:-1]
        elif parts[-1].startswith("_"):
            # Private modules (e.g. `codec._keccak`) are not part of the public API.
            continue
        if len(parts) < 2:
            # The root package. It would render to `reference/index.md`, which is the section's
            # own landing page — the one listing every module — so letting it through would have
            # the two overwrite each other. The package's docstring is already the front page of
            # the book (`docs/index.md`), so nothing is lost by skipping it here.
            continue
        # A package owns its directory's `index.md`; a module owns a page named after it. The
        # two take different slices of `parts` -- `entry` is the path *below* `reference/`, which
        # a package needs whole and a module needs without its own name.
        entry = "/".join(parts[1:])
        page = f"{entry}/index.md" if package else f"{entry}.md"
        found.append((tuple(parts), page))

    # **Two modules can want the same page, and one would silently win.** A package's
    # `__init__.py` and a module beside it called `index.py` both map to that directory's
    # `index.md`, so a page would be overwritten by whichever came second — in a dict, without a
    # trace. Only mdbook noticed, and only because it refuses a duplicate in its summary. Naming
    # it here means the next such module is a red build rather than a page nobody wrote being
    # quietly replaced by one nobody read.
    claims: dict[str, tuple[str, ...]] = {}
    for module_parts, module_page in found:
        if module_page in claims:
            raise AssertionError(
                f"{'.'.join(module_parts)} and {'.'.join(claims[module_page])} both render to "
                f"{module_page}; rename one, because a page can only hold one module"
            )
        claims[module_page] = module_parts
    return found


def _public(member: griffe.Object | griffe.Alias) -> TypeGuard[griffe.Object]:
    """Whether a member belongs on a reference page, and is something with a page of its own.

    An alias is something the module imported rather than defined, and a reference page that
    listed it would give the same object a page under every module that re-exports it.

    It is a `TypeGuard` rather than a plain `bool` because griffe models an imported name and a
    defined one as different types: without this the filter narrows nothing, and every caller has
    to say "and it is not an alias" again to satisfy the checker.
    """
    return not member.name.startswith("_") and not member.is_alias


def _plain(text: str) -> str:
    """Docstring prose, with the cross-reference roles taken out.

    The docstrings are written for the house style, which uses Sphinx roles — ``:class:`Foo```,
    ``:mod:`chainlens.models.flows```. mkdocstrings resolved those into links; **markdown has no
    such thing**, so left alone they render as the literal markup on every page, 195 times over.

    The target is kept and the role is dropped. That is the honest reduction: the role was a
    cross-reference this reference cannot make, and a reader is better served by the name than by
    the syntax that used to point at it. A leading ``~`` is Sphinx's "show only the last
    component", which is why it goes too.
    """
    return re.sub(r":[a-z]+:`~?([^`]+)`", r"`\1`", text)


def _fence(text: str, language: str = "python") -> str:
    return f"```{language}\n{text}\n```"


def _signature(obj: griffe.Object) -> str | None:
    """The object's signature as source, or ``None`` for something that has none.

    ``signature`` is a method on griffe 2.x rather than a property, which is worth knowing: the
    bound method prints as ``<bound method ...>`` and would land in a page verbatim.
    """
    signature = getattr(obj, "signature", None)
    if not callable(signature):
        return None
    rendered = signature()
    return str(rendered) if rendered else None


def _annotation(value: object) -> str:
    """A parameter or return annotation as it should read, or nothing when it is absent."""
    return f"`{value}`" if value else ""


def _parameters(items: list[object], *, heading: str) -> list[str]:
    """A parameter or attribute table, as a definition list.

    One shape for both, because ``Args:`` and ``Attributes:`` are the same kind of statement in a
    docstring and rendering them differently would be a distinction the writer did not make.
    """
    if not items:
        return []
    lines = [f"**{heading}**", ""]
    for item in items:
        name = getattr(item, "name", "")
        annotation = _annotation(getattr(item, "annotation", None))
        default = getattr(item, "default", None)
        described = " ".join(_plain(str(getattr(item, "description", ""))).split())
        lead = f"- `{name}`"
        if annotation:
            lead += f" {annotation}"
        if default is not None:
            lead += f", default `{default}`"
        lines.append(f"{lead} — {described}" if described else lead)
    lines.append("")
    return lines


def _docstring(obj: griffe.Object, *, heading: str = "Parameters") -> list[str]:
    """The docstring's sections as markdown, in the order the writer put them.

    Section kinds this does not know are rendered as their own text when they have any, rather
    than dropped: a docstring section that disappears silently is documentation the library
    believed it had.
    """
    docstring = getattr(obj, "docstring", None)
    if docstring is None:
        return []

    lines: list[str] = []
    for section in docstring.parse("google"):
        kind = section.kind
        if kind is griffe.DocstringSectionKind.text:
            lines += [_plain(str(section.value)).strip(), ""]
        elif kind in (
            griffe.DocstringSectionKind.parameters,
            griffe.DocstringSectionKind.attributes,
        ):
            lines += _parameters(
                list(section.value),
                heading="Attributes" if kind is griffe.DocstringSectionKind.attributes else heading,
            )
        elif kind in (
            griffe.DocstringSectionKind.returns,
            griffe.DocstringSectionKind.yields,
            griffe.DocstringSectionKind.receives,
        ):
            title = {
                griffe.DocstringSectionKind.returns: "Returns",
                griffe.DocstringSectionKind.yields: "Yields",
                griffe.DocstringSectionKind.receives: "Receives",
            }[kind]
            lines += _parameters(list(section.value), heading=title)
        elif kind is griffe.DocstringSectionKind.raises:
            lines += ["**Raises**", ""]
            for item in section.value:
                described = " ".join(_plain(str(getattr(item, "description", ""))).split())
                lines.append(f"- `{getattr(item, 'annotation', '')}` — {described}")
            lines.append("")
        elif kind is griffe.DocstringSectionKind.admonition:
            value = section.value
            title = str(getattr(value, "title", "") or "").title()
            body = _plain(str(getattr(value, "contents", "") or "")).strip()
            quoted = [f"> {line}" for line in body.splitlines()]
            lines += [f"> **{title}**" if title else ">", *quoted, ""]
        elif kind is griffe.DocstringSectionKind.examples:
            for item in section.value:
                body = _plain(str(getattr(item, "value", ""))).strip()
                lines += ["**Examples**", "", _fence(body), ""]
        elif isinstance(section.value, str):
            lines += [_plain(section.value).strip(), ""]
    return lines


def _render_member(member: griffe.Object, depth: int) -> list[str]:
    """One class, function or attribute, and its own members when it has them."""
    heading = "#" * min(depth, _MAX_DEPTH)
    lines = [f"{heading} `{member.name}`", ""]

    signature = _signature(member)
    if signature:
        lines += [_fence(signature), ""]

    lines += _docstring(member)

    if isinstance(member, griffe.Class):
        children = [
            child
            for child in member.members.values()
            if _public(child) and not isinstance(child, griffe.Module)
        ]
        # An attribute with nothing said about it does not deserve a heading of its own. They are
        # listed instead, with the value where there is one -- which is what turns an enum from a
        # column of empty headings into its members, and its members are the whole of its API.
        bare = [c for c in children if isinstance(c, griffe.Attribute) and not c.docstring]
        if bare:
            lines += ["**Members**", ""]
            for listed in bare:
                value = f" = {listed.value}" if listed.value else ""
                lines.append(f"- `{listed.name}`{value}")
            lines.append("")
        for child in children:
            if child not in bare:
                lines += _render_member(child, depth + 1)
    return lines


def _render_module(module: griffe.Module, path: tuple[str, ...]) -> str:
    """One module's page: what it is, then what it defines."""
    dotted = ".".join(path)
    lines = [f"# `{dotted}`", ""]
    lines += _docstring(module)

    members = [
        m for m in module.members.values() if _public(m) and not isinstance(m, griffe.Module)
    ]
    for member in sorted(members, key=lambda m: (not isinstance(m, griffe.Class), m.name)):
        lines += _render_member(member, 2)
    return "\n".join(lines).rstrip() + "\n"


def _render_index(modules: list[tuple[tuple[str, ...], str]]) -> str:
    """The reference section's landing page: every module, by what it is for."""
    lines = [
        "# API reference",
        "",
        "Every public module, rendered from its own docstrings. **This section is generated** —",
        "the docstrings in `src/chainlens/` are the single description, and editing a page here",
        "would be editing a copy. See `tests/docs/gen_reference.py`.",
        "",
    ]
    for parts, page in modules:
        lines.append(f"- [`{'.'.join(parts)}`]({page})")
    return "\n".join(lines).rstrip() + "\n"


def render_reference() -> dict[str, str]:
    """Every reference page, as ``docs/reference/...`` -> markdown."""
    root = _load()
    modules = _modules()
    pages: dict[str, str] = {"docs/reference/index.md": _render_index(modules)}
    for parts, page in modules:
        node: griffe.Object = root
        for part in parts[1:]:
            node = node[part]
        pages[f"docs/reference/{page}"] = _render_module(node, parts)  # type: ignore[arg-type]
    return pages


def _summary_block(modules: list[tuple[tuple[str, ...], str]]) -> list[str]:
    """The reference half of ``SUMMARY.md``, nested the way the module tree is."""
    lines = [BEGIN, "- [chainlens](reference/index.md)"]
    for parts, page in modules:
        if len(parts) == 1:
            continue
        indent = "  " * (len(parts) - 1)
        lines.append(f"{indent}- [{parts[-1]}](reference/{page})")
    lines.append(END)
    return lines


def render_summary(existing: str, modules: list[tuple[tuple[str, ...], str]]) -> str:
    """``SUMMARY.md`` with its generated block replaced, and the guide left alone.

    The guide half is hand-written and stays that way: it is prose about the library, and a writer
    adding a page to it should be editing markdown rather than a Python list. Only the part that
    has to track the source tree is generated.
    """
    lines = existing.splitlines()
    before = lines[: lines.index(BEGIN)] if BEGIN in lines else lines
    after = lines[lines.index(END) + 1 :] if END in lines else []
    return "\n".join([*before, *_summary_block(modules), *after]).rstrip() + "\n"


def render_all() -> dict[str, str]:
    """Every generated file, as repo-relative path -> contents.

    Includes ``SUMMARY.md``, so the test that compares this against the committed tree covers the
    table of contents as well as the pages: a module added without its entry appearing in the book
    is the same staleness as a module added without its page.
    """
    modules = _modules()
    rendered = render_reference()
    rendered["docs/SUMMARY.md"] = render_summary(SUMMARY.read_text(encoding="utf-8"), modules)
    return rendered


def write_all() -> list[Path]:
    """Write every generated file, and say which. Returns what it wrote."""
    written: list[Path] = []
    for relative, text in sorted(render_all().items()):
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_all():
        print(f"wrote {path.relative_to(ROOT)}")
