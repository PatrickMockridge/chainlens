"""Where declared annotations live: one JSON file per annotation, in a directory.

The format follows the case study's claim records — a directory of one-record-per-file JSON,
each carrying its own ``schema_version`` — and for the same reasons. A single file per record
diffs cleanly in git, never conflicts on a merge, and can be deleted by deleting a file.
The alternative, one growing array, turns every addition into a whole-file diff and every
concurrent edit into a conflict over the file rather than over the record.

JSON rather than TOML, which is the one place this differs from the case study. An
annotation's target and its provenance are nested models, and JSON is what pydantic
round-trips exactly; the case study's hand-rolled counterpart shows what it costs to parse a
nested model out of TOML by hand.

Nothing here decides whether an annotation is *true* or how much it is worth. The store is
about persistence, and the model is what constrains what may be asserted.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from chainlens.exceptions import ChainlensError
from chainlens.models.annotate import Annotation

__all__ = ["AnnotationStore", "AnnotationStoreError"]


class AnnotationStoreError(ChainlensError):
    """An annotation directory could not be read or written."""


class AnnotationStore:
    """A directory of annotation records.

    Args:
        directory: where the records live. Created on first write, not on construction —
            reading a directory that does not exist yet is an empty corpus rather than an
            error, because a first run has no annotations and that is not a failure.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        """Where the records live."""
        return self._directory

    def exists(self) -> bool:
        """Whether the directory has been created."""
        return self._directory.is_dir()

    def _paths(self) -> Iterator[Path]:
        if not self._directory.is_dir():
            return
        yield from sorted(self._directory.glob("*.json"))

    def load(self) -> tuple[Annotation, ...]:
        """Every record, oldest name first.

        Raises:
            AnnotationStoreError: a record is unreadable or does not validate. **Not**
                skipped: an annotation that cannot be read is a broken artifact, and quietly
                ignoring it would mean the graph renders a corpus with a hole nobody knows
                about. The message names the file.
        """
        loaded: list[Annotation] = []
        for path in self._paths():
            try:
                loaded.append(Annotation.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError) as exc:
                raise AnnotationStoreError(f"{path} is not a readable annotation: {exc}") from exc
        return tuple(loaded)

    def append(self, annotation: Annotation) -> Annotation:
        """Write one record, returning it.

        Idempotent: the identifier is content-addressed, so recording the same assertion twice
        writes the same file with the same bytes rather than accumulating duplicates.
        """
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._directory / f"{annotation.id.removeprefix('annotation:')}.json"
            path.write_text(
                json.dumps(json.loads(annotation.model_dump_json()), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise AnnotationStoreError(f"could not write to {self._directory}: {exc}") from exc
        return annotation

    def extend(self, annotations: Sequence[Annotation]) -> tuple[Annotation, ...]:
        """Write several records."""
        return tuple(self.append(annotation) for annotation in annotations)
