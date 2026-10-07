# `chainlens.models.entities`

Clusters, labels, and the evidence that justifies them.

A cluster is a *hypothesis*, not a fact. Every merge carries the heuristic that
produced it and a confidence in ``[0, 1]``, and every entity aggregates the
evidence for its construction. This is what separates a defensible tool from one
that launders a guess into an assertion: a consumer can always ask "why do you
believe these addresses belong together", and get an answer with a number on it.

## `Entity`

A cluster of addresses believed to share a controller.

``confidence`` is the aggregate belief that the cluster is correct;
``heuristics`` names the heuristics that built it and ``evidence`` carries
their individual justifications.

**Members**

- `id`
- `chain`
- `kind` = EntityKind.UNKNOWN
- `addresses` = Field(default_factory=frozenset)
- `labels` = ()
- `confidence` = Field(default=0.0, ge=0.0, le=1.0)
- `heuristics` = ()
- `evidence` = ()
- `provenance` = None
- `address_count`
- `is_labeled`

## `Evidence`

Why a heuristic asserted something.

``detail`` holds the heuristic-specific signals that fired (e.g. matching
script types, input count), so a reviewer can disagree with the reasoning
rather than just the conclusion.

**Members**

- `heuristic`
- `confidence` = Field(ge=0.0, le=1.0)
- `detail` = Field(default_factory=dict)
- `txids` = ()

## `HeuristicResult`

What one heuristic produced in a single run.

``change_flags`` maps a transaction id to the vault indices the change
heuristic identified as change. Those indices are folded back into the
sender's own cluster by the clustering engine, which is why they are returned
separately from merges rather than as merges themselves.

**Members**

- `heuristic`
- `merges` = ()
- `labels` = ()
- `change_flags` = Field(default_factory=dict)
- `warnings` = ()
- `elapsed_seconds` = None
- `merge_count`
- `is_empty`

## `Label`

An attribution attached to an address or entity.

``source`` records whether this came from a provider, the user, a heuristic
or an import -- the difference between an exchange confirming an address and
a guess. ``address`` is set when the label applies to one address only.

**Attributes**

- `provider` `str | None` — *which* source asserted this — ``"ofac-sdn"``, ``"events"``, an adapter's name. ``source`` says a third party is responsible; once several are merged into one answer, that is no longer enough to act on, and the difference between a sanctions list and a curated file is not one a reader should have to infer from a URL.
- `url` `str | None` — where the assertion can be read. For a curated label this is the citation, and a label with no URL is an assertion nobody can check.

**Members**

- `name`
- `source`
- `kind` = EntityKind.UNKNOWN
- `confidence` = Field(default=None, ge=0.0, le=1.0)
- `address` = None
- `url` = None
- `provider` = None

## `Merge`

An assertion that two or more addresses share a controller.

**Members**

- `addresses` = Field(default_factory=frozenset)
- `confidence` = Field(ge=0.0, le=1.0)
- `evidence`
