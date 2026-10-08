"""Address labels: who says an address is what.

The first implementation of :data:`~chainlens.providers.capabilities.Capability.LABELS` in this
tree. Before it, ``check_label`` could only ever answer "no label source is configured", so an
attribution claim was unanswerable by construction.

The shape of the answer is the point, and it is the same one the rest of the library makes: **a
label is an assertion by somebody, with a citation**, never a fact the library knows. Two sources
that disagree both appear, each naming who said it, because deciding between them is a reader's
call and not one this code has the standing to make.

See :mod:`chainlens.labels.records` for the file format and :mod:`chainlens.labels.provider` for
why the data is committed rather than fetched.
"""

from __future__ import annotations

from chainlens.labels.provider import LocalLabelProvider
from chainlens.labels.records import (
    DATA_DIR,
    LabelFile,
    LabelRecord,
    RecordError,
    load_directory,
    load_file,
)

__all__ = [
    "DATA_DIR",
    "LabelFile",
    "LabelRecord",
    "LocalLabelProvider",
    "RecordError",
    "load_directory",
    "load_file",
]
