"""Order-preserving "several rows collapse into one because they share a
key" dedup, shared by ``hybrid_search.reciprocal_rank_fusion()`` (rows that
appear in more than one ranked list) and
``parent_chunk_expansion.expand_to_parent_chunks()`` (child chunks that
share a parent) -- both already documented each other as using "the same
'first occurrence wins' rule" before this module existed to hold it once.

    - ``group_by_key()`` -- the core grouping: every row that shares a key
      ends up in one list, in the order that key first appeared.
    - ``first_occurrence_map()`` -- the common special case where a caller
      only wants the first row for each key (``reciprocal_rank_fusion()``'s
      use), built on top of ``group_by_key()``.
"""
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Union

KeyFn = Union[str, Callable[[dict], Any]]


def _key_fn(key: KeyFn) -> Callable[[dict], Any]:
    return key if callable(key) else (lambda row: row[key])


def group_by_key(rows: List[dict], key: KeyFn) -> "OrderedDict[Any, List[dict]]":
    """Group ``rows`` by ``key(row)`` (or ``row[key]`` when ``key`` is a
    string), preserving both the order rows share a group in and the order
    each distinct key first appears in ``rows``.

    This is ``parent_chunk_expansion.expand_to_parent_chunks()``'s dedup
    step: group child chunks by ``rowParentGUID``, so every chunk sharing a
    parent ends up together and that parent is only fetched/sent once.
    """
    key_fn = _key_fn(key)
    groups: "OrderedDict[Any, List[dict]]" = OrderedDict()
    # deduplication-step: every row lands in its key's group instead of its
    # own entry, so rows sharing a key collapse together on the first one seen.
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    return groups


def first_occurrence_map(rows: List[dict], key: KeyFn) -> "OrderedDict[Any, dict]":
    """Map each distinct ``key(row)`` to the *first* row in ``rows`` that
    had it, in the order each key first appears -- ``rows`` after the first
    sharing a key are discarded rather than grouped (use ``group_by_key()``
    to keep them).

    This is ``hybrid_search.reciprocal_rank_fusion()``'s dedup step: several
    ranked lists can return the same row (by ``rowGUID``), and the fused
    result keeps one representative copy per row, whichever list saw it
    first.
    """
    # deduplication-step: keep only the first row of each group, discarding
    # every later row that shared its key.
    return OrderedDict((k, group[0]) for k, group in group_by_key(rows, key).items())
