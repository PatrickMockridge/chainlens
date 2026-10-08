# `chainlens.analysis.heuristics`

Clustering heuristics.

Each heuristic reasons over a fixed `chainlens.analysis.heuristics.base.HeuristicContext`
and reports merges, labels and change flags. None of them has network access, so
they are pure functions of the data the engine gathered and are trivially
testable.
