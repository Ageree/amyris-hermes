"""Bounded, process-local idempotency store for the Phase-1A skeleton.

A naive `set` grows without bound: any third party can flood distinct
`message_handle`s and exhaust memory. This caps the store at `maxsize` and
evicts the oldest entry FIFO when full (an LRU-ish bound built on
`collections.OrderedDict`, which preserves insertion order).

P1C moves durable, multi-user idempotency to Convex; this is a throwaway spike.
"""
from __future__ import annotations

from collections import OrderedDict

DEFAULT_MAXSIZE = 2000


class BoundedDedup:
    """Fixed-capacity seen-set. `add` returns True if the key is NEW."""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._store: "OrderedDict[str, None]" = OrderedDict()

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)

    def add(self, key: str) -> bool:
        """Record `key`. Returns True if it was newly added, False if a dup.

        On insert past capacity, evicts the oldest key (FIFO).
        """
        if key in self._store:
            return False
        self._store[key] = None
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)  # evict oldest
        return True
