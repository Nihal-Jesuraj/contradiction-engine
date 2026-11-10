"""Stable merge sort and iterative binary-search bounds.

The project deliberately avoids Python's ``sorted`` and ``list.sort`` so the
sorting requirement is satisfied by code we can explain line by line.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


def merge_sort(items: list[T], key: Callable[[T], Any] | None = None) -> list[T]:
    """Sort a list stably with merge sort.

    Inputs: ``items`` and an optional ``key`` function.
    Outputs: a new sorted list; the input list is not modified.
    Complexity: O(n log n) time, O(n) peak auxiliary space.
    """
    key_function = key if key is not None else _identity
    if len(items) <= 1:
        return list(items)
    middle = len(items) // 2
    left = merge_sort(items[:middle], key_function)
    right = merge_sort(items[middle:], key_function)
    return _merge(left, right, key_function)


def _identity(value: Any) -> Any:
    """Return a value unchanged, used when no key function is supplied."""
    return value


def _merge(
    left: list[T],
    right: list[T],
    key: Callable[[T], Any],
) -> list[T]:
    """Merge two sorted lists, keeping equal keys in their original order.

    Inputs: two sorted lists and the key function.
    Outputs: one sorted list.
    Complexity: O(len(left) + len(right)) time and space.
    """
    merged: list[T] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        # ``<=`` takes from the left list first, which is what makes the
        # sort stable when two items share the same key.
        if key(left[left_index]) <= key(right[right_index]):
            merged.append(left[left_index])
            left_index += 1
        else:
            merged.append(right[right_index])
            right_index += 1
    merged.extend(left[left_index:])
    merged.extend(right[right_index:])
    return merged


def lower_bound(
    items: list[T],
    target: Any,
    key: Callable[[T], Any] | None = None,
) -> int:
    """Return the first index whose key is greater than or equal to target.

    Inputs: a list sorted by ``key``, a target value, and the key function.
    Outputs: an index in ``[0, len(items)]``.
    Complexity: O(log n) time, O(1) space.
    """
    key_function = key if key is not None else _identity
    low = 0
    high = len(items)
    while low < high:
        middle = (low + high) // 2
        if key_function(items[middle]) < target:
            low = middle + 1
        else:
            high = middle
    return low


def upper_bound(
    items: list[T],
    target: Any,
    key: Callable[[T], Any] | None = None,
) -> int:
    """Return the first index whose key is strictly greater than target.

    Inputs: a list sorted by ``key``, a target value, and the key function.
    Outputs: an index in ``[0, len(items)]``.
    Complexity: O(log n) time, O(1) space.
    """
    key_function = key if key is not None else _identity
    low = 0
    high = len(items)
    while low < high:
        middle = (low + high) // 2
        if key_function(items[middle]) <= target:
            low = middle + 1
        else:
            high = middle
    return low
