"""Generate the API reference section from the package tree.

Run by the ``mkdocs-gen-files`` plugin at build time. Generating the reference
(and its navigation) from the source layout means it can never go stale: a new
module appears in the docs automatically.

Every page is an ``::: module.path`` directive, which ``mkdocstrings`` resolves.
"""

from __future__ import annotations

from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()

root = Path(__file__).parent.parent
source_root = root / "src"

for path in sorted(source_root.rglob("*.py")):
    module_path = path.relative_to(source_root).with_suffix("")
    doc_path = path.relative_to(source_root).with_suffix(".md")
    full_doc_path = Path("reference", doc_path)

    parts = tuple(module_path.parts)

    if parts[-1] == "py.typed":
        continue
    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    elif parts[-1].startswith("_"):
        # Private modules (e.g. codec._keccak) are not part of the public API.
        continue

    if not parts:
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as handle:
        handle.write(f"::: {'.'.join(parts)}\n")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))

with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
