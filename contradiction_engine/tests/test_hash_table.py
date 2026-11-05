"""Tests for the hand-written chaining hash table."""

from __future__ import annotations

import pytest

from contradiction_engine.algorithms.hash_table import HashTable


def test_empty_table_returns_default() -> None:
    """A missing key returns the caller's default."""
    table: HashTable = HashTable()
    assert table.get("missing") is None
    assert table.get("missing", "fallback") == "fallback"
    assert len(table) == 0
    assert "missing" not in table


def test_put_get_and_update() -> None:
    """Inserting an existing key replaces its value without growing the table."""
    table: HashTable = HashTable()
    table.put("alice", 1)
    table.put("bob", 2)
    table.put("alice", 3)
    assert table.get("alice") == 3
    assert table.get("bob") == 2
    assert len(table) == 2
    assert "alice" in table


def test_collisions_use_chaining() -> None:
    """A one-bucket table forces collisions and still stores every pair."""
    table: HashTable = HashTable(capacity=1)
    for index in range(6):
        table.put(f"key-{index}", index)
    assert len(table) == 6
    for index in range(6):
        assert table.get(f"key-{index}") == index
    assert table.capacity > 1
    assert table.load_factor <= 0.75


def test_resize_preserves_pairs() -> None:
    """Growing the bucket array keeps every key and value reachable."""
    table: HashTable = HashTable(capacity=2)
    expected = {f"person-{index}": index for index in range(50)}
    for key, value in expected.items():
        table.put(key, value)
    assert len(table) == len(expected)
    assert table.capacity > 2
    for key, value in expected.items():
        assert table.get(key) == value


def test_remove() -> None:
    """Removing a key reports success once and leaves other keys intact."""
    table: HashTable = HashTable()
    table.put("a", 1)
    table.put("b", 2)
    assert table.remove("a") is True
    assert table.remove("a") is False
    assert table.get("a") is None
    assert table.get("b") == 2
    assert len(table) == 1


def test_keys_values_items_and_iteration() -> None:
    """The collection views expose exactly the stored pairs."""
    table: HashTable = HashTable()
    table.put("a", 1)
    table.put("b", 2)
    assert set(table.keys()) == {"a", "b"}
    assert set(table.values()) == {1, 2}
    assert set(table.items()) == {("a", 1), ("b", 2)}
    assert set(iter(table)) == {"a", "b"}


def test_invalid_capacity_is_rejected() -> None:
    """A table needs at least one bucket."""
    with pytest.raises(ValueError):
        HashTable(capacity=0)


def test_longest_chain_reports_the_largest_bucket() -> None:
    """An empty table has no chain, and inserts are reflected in the report."""
    table: HashTable = HashTable()
    assert table.longest_chain() == 0
    table.put("a", 1)
    assert table.longest_chain() == 1
    many: HashTable = HashTable(capacity=64)
    for index in range(20):
        many.put(f"key-{index}", index)
    assert 1 <= many.longest_chain() <= 20
