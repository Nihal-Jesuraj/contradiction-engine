"""A binary min-heap written from scratch.

Dijkstra uses this heap. Instead of a decrease-key operation, the graph code
pushes a new entry when a shorter distance is found and skips stale entries
when they are popped ("lazy deletion").
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class MinHeap(Generic[T]):
    """A binary min-heap ordered by a numeric priority.

    Inputs: none.
    Outputs: a mutable heap.
    Complexity: O(log n) push/pop, O(1) peek, O(n) space.
    """

    def __init__(self) -> None:
        """Create an empty heap.

        Inputs: none.
        Outputs: none.
        Complexity: O(1) time and space.
        """
        # Each entry is (priority, insertion_order, value). The insertion
        # counter breaks ties without comparing the values themselves.
        self._entries: list[tuple[float, int, T]] = []
        self._next_order = 0

    def push(self, priority: float, value: T) -> None:
        """Insert a value with the given priority.

        Inputs: ``priority`` and ``value``.
        Outputs: none.
        Complexity: O(log n) time, O(1) extra space.
        """
        entry = (priority, self._next_order, value)
        self._next_order += 1
        self._entries.append(entry)
        self._sift_up(len(self._entries) - 1)

    def pop(self) -> T:
        """Remove and return the value with the smallest priority.

        Inputs: none.
        Outputs: the stored value.
        Complexity: O(log n) time, O(1) extra space.
        Raises IndexError when the heap is empty.
        """
        if not self._entries:
            raise IndexError("pop from empty heap")
        smallest = self._entries[0]
        last = self._entries.pop()
        if self._entries:
            self._entries[0] = last
            self._sift_down(0)
        return smallest[2]

    def peek(self) -> T:
        """Return the smallest value without removing it.

        Inputs: none.
        Outputs: the stored value.
        Complexity: O(1) time and space.
        Raises IndexError when the heap is empty.
        """
        if not self._entries:
            raise IndexError("peek from empty heap")
        return self._entries[0][2]

    def _sift_up(self, index: int) -> None:
        """Move an entry upward until its parent is smaller.

        Inputs: the index of the entry to move.
        Outputs: none.
        Complexity: O(log n) time, O(1) space.
        """
        while index > 0:
            parent = (index - 1) // 2
            if self._entries[parent] <= self._entries[index]:
                return
            self._entries[parent], self._entries[index] = (
                self._entries[index],
                self._entries[parent],
            )
            index = parent

    def _sift_down(self, index: int) -> None:
        """Move an entry downward until both children are larger.

        Inputs: the index of the entry to move.
        Outputs: none.
        Complexity: O(log n) time, O(1) space.
        """
        size = len(self._entries)
        while True:
            left = 2 * index + 1
            smallest = index
            if left < size and self._entries[left] < self._entries[smallest]:
                smallest = left
            right = left + 1
            if right < size and self._entries[right] < self._entries[smallest]:
                smallest = right
            if smallest == index:
                return
            self._entries[index], self._entries[smallest] = (
                self._entries[smallest],
                self._entries[index],
            )
            index = smallest

    def is_empty(self) -> bool:
        """Return True when no entries are stored."""
        return not self._entries

    def __len__(self) -> int:
        """Return the number of stored entries."""
        return len(self._entries)
