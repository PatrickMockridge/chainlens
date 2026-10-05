"""Union-find invariants.

The property tests matter more than the examples here: a clustering engine's
correctness rests entirely on the disjoint-set behaving as a partition, and a
subtle path-compression bug would show up as two addresses that "are" and "are
not" in the same cluster depending on the order they are queried.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from chainlens.analysis.clustering import UnionFind

PAIR = st.tuples(st.integers(0, 12), st.integers(0, 12))


def test_find_registers_an_unknown_item() -> None:
    union_find = UnionFind()
    assert union_find.find("a") == "a"
    assert "a" in union_find
    assert len(union_find) == 1


def test_unknown_items_are_not_connected() -> None:
    union_find = UnionFind()
    assert not union_find.connected("a", "b")
    union_find.add("a")
    assert not union_find.connected("a", "b")


def test_union_merges_and_reports_novelty() -> None:
    union_find = UnionFind()
    assert union_find.union("a", "b") is True
    assert union_find.union("a", "b") is False  # already together
    assert union_find.connected("a", "b")


def test_union_is_transitive() -> None:
    union_find = UnionFind()
    union_find.union("a", "b")
    union_find.union("b", "c")
    assert union_find.connected("a", "c")
    assert union_find.members("a") == frozenset({"a", "b", "c"})


def test_lone_item_is_its_own_cluster() -> None:
    union_find = UnionFind()
    assert union_find.members("lonely") == frozenset({"lonely"})


def test_components_map_representatives_to_members() -> None:
    union_find = UnionFind()
    union_find.union("a", "b")
    union_find.add("c")
    components = union_find.components()
    assert sorted(sorted(group) for group in components.values()) == [["a", "b"], ["c"]]


@given(st.lists(PAIR, max_size=40))
def test_components_always_form_a_partition(pairs: list[tuple[int, int]]) -> None:
    union_find = UnionFind()
    for left, right in pairs:
        union_find.union(str(left), str(right))

    components = list(union_find.components().values())
    members = [member for group in components for member in group]

    # Every registered item appears in exactly one component.
    assert len(members) == len(set(members)) == len(union_find)
    assert set(members) == {str(i) for pair in pairs for i in pair}


@given(st.lists(PAIR, max_size=40))
def test_membership_is_consistent_and_symmetric(pairs: list[tuple[int, int]]) -> None:
    union_find = UnionFind()
    for left, right in pairs:
        union_find.union(str(left), str(right))

    for group in union_find.components().values():
        for first in group:
            assert union_find.members(first) == group
            for second in group:
                assert union_find.connected(first, second)
                assert union_find.connected(second, first)


@given(st.lists(PAIR, max_size=40))
def test_union_is_order_independent(pairs: list[tuple[int, int]]) -> None:
    """Unioning the same edges in any order must give the same partition."""
    forward = UnionFind()
    for left, right in pairs:
        forward.union(str(left), str(right))

    backward = UnionFind()
    for left, right in reversed(pairs):
        backward.union(str(left), str(right))

    def normalise(union_find: UnionFind) -> list[list[str]]:
        return sorted(sorted(group) for group in union_find.components().values())

    assert normalise(forward) == normalise(backward)
