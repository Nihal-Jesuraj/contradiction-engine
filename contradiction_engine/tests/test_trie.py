"""Tests for the optional prefix trie."""

from __future__ import annotations

from contradiction_engine.algorithms.trie import Trie


def test_insert_and_contains() -> None:
    trie = Trie()
    trie.insert("harbour", "R1")
    assert trie.contains("harbour")
    assert not trie.contains("harbo")
    assert not trie.contains("dock")


def test_starts_with() -> None:
    trie = Trie()
    trie.insert("station", "R1")
    assert trie.starts_with("stat")
    assert trie.starts_with("station")
    assert not trie.starts_with("statx")


def test_words_with_prefix() -> None:
    trie = Trie()
    for word in ["dock", "doctor", "dog", "market"]:
        trie.insert(word, word)
    assert set(trie.words_with_prefix("do")) == {"dock", "doctor", "dog"}
    assert trie.words_with_prefix("zz") == []


def test_record_ids_with_prefix_are_deduplicated() -> None:
    trie = Trie()
    trie.insert("harbour", "R1")
    trie.insert("harbour", "R1")
    trie.insert("harbour", "R2")
    assert set(trie.record_ids_with_prefix("har")) == {"R1", "R2"}
