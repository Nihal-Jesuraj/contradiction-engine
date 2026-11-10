"""Tests for the binary min-heap."""

from __future__ import annotations

import pytest

from contradiction_engine.algorithms.min_heap import MinHeap


def test_pop_returns_values_in_priority_order() -> None:
    """Values come out from smallest priority to largest."""
    heap: MinHeap[str] = MinHeap()
    for priority, value in [(5, "five"), (1, "one"), (3, "three")]:
        heap.push(priority, value)
    assert [heap.pop(), heap.pop(), heap.pop()] == ["one", "three", "five"]


def test_duplicate_priorities_are_all_returned() -> None:
    """Ties are allowed and every value is returned."""
    heap: MinHeap[str] = MinHeap()
    heap.push(2, "a")
    heap.push(2, "b")
    heap.push(1, "c")
    assert [heap.pop(), heap.pop(), heap.pop()] == ["c", "a", "b"]


def test_peek_does_not_remove() -> None:
    """Peek returns the minimum and leaves the size unchanged."""
    heap: MinHeap[int] = MinHeap()
    heap.push(4, 40)
    heap.push(2, 20)
    assert heap.peek() == 20
    assert len(heap) == 2


def test_empty_heap_raises() -> None:
    """Popping or peeking an empty heap is an error."""
    heap: MinHeap[int] = MinHeap()
    assert heap.is_empty()
    with pytest.raises(IndexError):
        heap.pop()
    with pytest.raises(IndexError):
        heap.peek()
