"""A compact prefix trie for the explorer's keyword filter.

Each word points at the records that contain it, so a prefix query returns the
union of matching records. This is optional; the rest of the project works
without it.
"""

from __future__ import annotations


class TrieNode:
    """One character position in the trie."""

    __slots__ = ("children", "is_word", "record_ids")

    def __init__(self) -> None:
        """Create an empty node."""
        self.children: dict[str, "TrieNode"] = {}
        self.is_word = False
        self.record_ids: list[str] = []


class Trie:
    """A prefix tree over lowercase words.

    Inputs: none.
    Outputs: a mutable trie.
    Complexity: O(total characters) space.
    """

    def __init__(self) -> None:
        """Create an empty trie."""
        self.root = TrieNode()

    def insert(self, word: str, record_id: str) -> None:
        """Insert a word and remember which record contained it.

        Inputs: ``word`` and ``record_id``.
        Outputs: none.
        Complexity: O(len(word)) time, O(len(word)) space.
        """
        node = self.root
        for character in word:
            child = node.children.get(character)
            if child is None:
                child = TrieNode()
                node.children[character] = child
            node = child
        node.is_word = True
        if record_id not in node.record_ids:
            node.record_ids.append(record_id)

    def _find(self, prefix: str) -> TrieNode | None:
        """Return the node at the end of ``prefix``, or None."""
        node = self.root
        for character in prefix:
            node = node.children.get(character)
            if node is None:
                return None
        return node

    def contains(self, word: str) -> bool:
        """Return True when the exact word was inserted.

        Complexity: O(len(word)) time, O(1) space.
        """
        node = self._find(word)
        return node is not None and node.is_word

    def starts_with(self, prefix: str) -> bool:
        """Return True when at least one word starts with ``prefix``.

        Complexity: O(len(prefix)) time, O(1) space.
        """
        return self._find(prefix) is not None

    def words_with_prefix(self, prefix: str) -> list[str]:
        """Return every word below ``prefix`` in depth-first order.

        Complexity: O(len(prefix) + output) time and space.
        """
        node = self._find(prefix)
        if node is None:
            return []
        words: list[str] = []
        self._collect(node, prefix, words)
        return words

    def _collect(
        self,
        node: TrieNode,
        prefix: str,
        words: list[str],
    ) -> None:
        """Depth-first walk that appends complete words."""
        if node.is_word:
            words.append(prefix)
        for character, child in node.children.items():
            self._collect(child, prefix + character, words)

    def record_ids_with_prefix(self, prefix: str) -> list[str]:
        """Return the IDs of records containing a word under ``prefix``.

        Complexity: O(len(prefix) + output) time and space.
        """
        node = self._find(prefix)
        if node is None:
            return []
        found: list[str] = []
        self._collect_ids(node, found)
        return found

    def _collect_ids(self, node: TrieNode, found: list[str]) -> None:
        """Depth-first walk that appends record IDs without duplicates."""
        for record_id in node.record_ids:
            if record_id not in found:
                found.append(record_id)
        for child in node.children.values():
            self._collect_ids(child, found)
