# `chainlens.labels`

Address labels: who says an address is what.

The first implementation of `chainlens.providers.capabilities.Capability.LABELS` in this
tree. Before it, ``check_label`` could only ever answer "no label source is configured", so an
attribution claim was unanswerable by construction.

The shape of the answer is the point, and it is the same one the rest of the library makes: **a
label is an assertion by somebody, with a citation**, never a fact the library knows. Two sources
that disagree both appear, each naming who said it, because deciding between them is a reader's
call and not one this code has the standing to make.

See `chainlens.labels.records` for the file format and `chainlens.labels.provider` for
why the data is committed rather than fetched.
