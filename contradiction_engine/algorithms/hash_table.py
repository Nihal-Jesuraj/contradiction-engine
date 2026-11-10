"""A separate-chaining hash table with a hand-written hash function.

Keys are strings. Values may be anything. The table is used by the detectors
to group records by device, person, or account without relying on Python's
built-in ``dict`` for the grouping operation itself.
"""

from __future__ import annotations

from typing import Any, Iterator

_FNV_OFFSET_BASIS = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK_64 = 0xFFFFFFFFFFFFFFFF
_MAX_LOAD_FACTOR = 0.75


class HashTable:
    """A hash table that stores ``(key, value)`` pairs in chained buckets.

    Inputs: an optional initial bucket count.
    Outputs: a mutable mapping-like object.
    Complexity: average O(1) per operation, O(n) worst case; O(n) space.
    """

    def __init__(self, capacity: int = 8) -> None:
        """Create an empty table.

        Inputs: ``capacity``, the number of buckets (at least 1).
        Outputs: none.
        Complexity: O(capacity) time and space.
        """
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._capacity = capacity
        self._buckets: list[list[tuple[str, Any]]] = [
            [] for _ in range(capacity)
        ]
        self._size = 0

    def _hash(self, key: str) -> int:
        """Compute the FNV-1a 64-bit hash of a key and map it to a bucket.

        Inputs: ``key``, the string to hash.
        Outputs: a bucket index in ``[0, capacity)``.
        Complexity: O(len(key)) time, O(1) space.
        """
        value = _FNV_OFFSET_BASIS
        for byte in key.encode("utf-8"):
            value ^= byte
            value = (value * _FNV_PRIME) & _MASK_64
        return value % self._capacity

    def put(self, key: str, value: Any) -> None:
        """Insert a pair, or replace the value if the key already exists.

        Inputs: ``key`` and ``value``.
        Outputs: none.
        Complexity: average O(1), worst O(n) when every key collides.
        """
        index = self._hash(key)
        bucket = self._buckets[index]
        for position, (existing_key, _) in enumerate(bucket):
            if existing_key == key:
                bucket[position] = (key, value)
                return
        bucket.append((key, value))
        self._size += 1
        if self._size / self._capacity > _MAX_LOAD_FACTOR:
            self._resize()

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value stored for ``key``, or ``default`` if absent.

        Inputs: ``key`` and an optional default.
        Outputs: the stored value or ``default``.
        Complexity: average O(1), worst O(n).
        """
        index = self._hash(key)
        for existing_key, value in self._buckets[index]:
            if existing_key == key:
                return value
        return default

    def contains(self, key: str) -> bool:
        """Return True when ``key`` is present.

        Inputs: ``key``.
        Outputs: a boolean.
        Complexity: average O(1), worst O(n).
        """
        index = self._hash(key)
        for existing_key, _ in self._buckets[index]:
            if existing_key == key:
                return True
        return False

    def remove(self, key: str) -> bool:
        """Delete ``key`` if present.

        Inputs: ``key``.
        Outputs: True when a pair was removed, False when the key was absent.
        Complexity: average O(1), worst O(n).
        """
        index = self._hash(key)
        bucket = self._buckets[index]
        for position, (existing_key, _) in enumerate(bucket):
            if existing_key == key:
                del bucket[position]
                self._size -= 1
                return True
        return False

    def keys(self) -> list[str]:
        """Return all keys in bucket order.

        Inputs: none.
        Outputs: a new list of keys.
        Complexity: O(capacity + n) time, O(n) space.
        """
        result: list[str] = []
        for bucket in self._buckets:
            for key, _ in bucket:
                result.append(key)
        return result

    def values(self) -> list[Any]:
        """Return all values in bucket order.

        Inputs: none.
        Outputs: a new list of values.
        Complexity: O(capacity + n) time, O(n) space.
        """
        result: list[Any] = []
        for bucket in self._buckets:
            for _, value in bucket:
                result.append(value)
        return result

    def items(self) -> list[tuple[str, Any]]:
        """Return all pairs in bucket order.

        Inputs: none.
        Outputs: a new list of ``(key, value)`` tuples.
        Complexity: O(capacity + n) time, O(n) space.
        """
        result: list[tuple[str, Any]] = []
        for bucket in self._buckets:
            for pair in bucket:
                result.append(pair)
        return result

    def _resize(self) -> None:
        """Double the bucket count and rehash every existing pair.

        Inputs: none.
        Outputs: none.
        Complexity: O(capacity + n) time, O(capacity + n) space.
        """
        old_buckets = self._buckets
        self._capacity *= 2
        self._buckets = [[] for _ in range(self._capacity)]
        self._size = 0
        for bucket in old_buckets:
            for key, value in bucket:
                self.put(key, value)

    @property
    def capacity(self) -> int:
        """Return the current number of buckets."""
        return self._capacity

    @property
    def load_factor(self) -> float:
        """Return ``size / capacity`` for inspection in tests and the UI."""
        return self._size / self._capacity

    def longest_chain(self) -> int:
        """Return the number of pairs in the largest bucket.

        Inputs: none.
        Outputs: a non-negative integer (0 for an empty table).
        Complexity: O(capacity) time, O(1) space.
        """
        longest = 0
        for bucket in self._buckets:
            if len(bucket) > longest:
                longest = len(bucket)
        return longest

    def __len__(self) -> int:
        """Return the number of stored pairs."""
        return self._size

    def __contains__(self, key: str) -> bool:
        """Support the ``key in table`` syntax."""
        return self.contains(key)

    def __iter__(self) -> Iterator[str]:
        """Iterate over keys in bucket order."""
        return iter(self.keys())
