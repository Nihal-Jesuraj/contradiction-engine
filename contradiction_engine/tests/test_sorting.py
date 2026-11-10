"""Tests for merge sort and binary-search bounds."""

from __future__ import annotations

import random

from contradiction_engine.algorithms.sorting import (
    lower_bound,
    merge_sort,
    upper_bound,
)


def test_empty_and_single_item() -> None:
    """Trivial inputs come back as new lists."""
    assert merge_sort([]) == []
    assert merge_sort([7]) == [7]


def test_duplicates_are_kept() -> None:
    """Duplicate keys are all preserved."""
    assert merge_sort([3, 1, 3, 2, 1]) == [1, 1, 2, 3, 3]


def test_stability_preserves_input_order_for_equal_keys() -> None:
    """Equal keys keep their original relative order."""
    records = [("b", 0), ("a", 1), ("b", 2), ("a", 3)]
    ordered = merge_sort(records, key=lambda pair: pair[0])
    assert ordered == [("a", 1), ("a", 3), ("b", 0), ("b", 2)]


def test_matches_python_sorted_on_random_lists() -> None:
    """Random lists match the reference implementation (tests may sort)."""
    rng = random.Random(7)
    values = [rng.randint(-20, 20) for _ in range(200)]
    assert merge_sort(values) == sorted(values)


def test_lower_bound_with_duplicates() -> None:
    """Lower bound points at the first equal value."""
    values = [1, 2, 2, 2, 5]
    assert lower_bound(values, 2) == 1
    assert lower_bound(values, 0) == 0
    assert lower_bound(values, 6) == len(values)
    assert lower_bound([], 3) == 0


def test_upper_bound_with_duplicates() -> None:
    """Upper bound points just past the last equal value."""
    values = [1, 2, 2, 2, 5]
    assert upper_bound(values, 2) == 4
    assert upper_bound(values, 5) == len(values)
    assert upper_bound(values, 0) == 0
    assert upper_bound([], 3) == 0


def test_bounds_accept_a_key_function() -> None:
    """Both bounds compare the derived key, not the container itself."""
    records = [("2026-01-01", "a"), ("2026-01-02", "b"), ("2026-01-02", "c")]
    key = lambda pair: pair[0]
    assert lower_bound(records, "2026-01-02", key=key) == 1
    assert upper_bound(records, "2026-01-02", key=key) == 3
