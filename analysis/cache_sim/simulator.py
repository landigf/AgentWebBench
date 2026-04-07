"""Cache eviction policy simulator.

Six policies: LRU, LFU, ARC, S3FIFO, WTinyLFU, GDSF.
All handle variable object sizes correctly.
"""

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
import heapq
import math


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    byte_hits: int = 0
    byte_misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / max(self.hits + self.misses, 1)

    @property
    def byte_hit_rate(self) -> float:
        return self.byte_hits / max(self.byte_hits + self.byte_misses, 1)


class CachePolicy(ABC):
    def __init__(self, capacity_bytes: int):
        self.capacity = capacity_bytes
        self.current_size = 0
        self.stats = CacheStats()

    def access(self, key: str, size: int) -> bool:
        """Process a cache access. Returns True if hit."""
        if size > self.capacity:
            # Object larger than entire cache: always miss, never admit
            self.stats.misses += 1
            self.stats.byte_misses += size
            return False

        hit = self._lookup(key)
        if hit:
            self.stats.hits += 1
            self.stats.byte_hits += size
        else:
            self.stats.misses += 1
            self.stats.byte_misses += size
            self._evict_until_fits(size)
            self._admit(key, size)
        return hit

    @abstractmethod
    def _lookup(self, key: str) -> bool:
        ...

    @abstractmethod
    def _admit(self, key: str, size: int) -> None:
        ...

    @abstractmethod
    def _evict_until_fits(self, size: int) -> None:
        ...


# ---------------------------------------------------------------------------
# 1. LRU — Least Recently Used
# ---------------------------------------------------------------------------
class LRU(CachePolicy):
    """LRU using OrderedDict. Move-to-end on hit, pop from front on evict."""

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self.cache: OrderedDict[str, int] = OrderedDict()  # key -> size

    def _lookup(self, key: str) -> bool:
        if key in self.cache:
            self.cache.move_to_end(key)
            return True
        return False

    def _admit(self, key: str, size: int) -> None:
        self.cache[key] = size
        self.current_size += size

    def _evict_until_fits(self, size: int) -> None:
        while self.current_size + size > self.capacity and self.cache:
            _, evicted_size = self.cache.popitem(last=False)
            self.current_size -= evicted_size
            self.stats.evictions += 1


# ---------------------------------------------------------------------------
# 2. LFU — Least Frequently Used
# ---------------------------------------------------------------------------
class LFU(CachePolicy):
    """LFU with frequency counters. Ties broken by insertion order."""

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self.cache: dict[str, int] = {}  # key -> size
        self.freq: dict[str, int] = {}  # key -> frequency
        self.order: dict[str, int] = {}  # key -> insertion counter
        self._counter = 0

    def _lookup(self, key: str) -> bool:
        if key in self.cache:
            self.freq[key] += 1
            return True
        return False

    def _admit(self, key: str, size: int) -> None:
        self.cache[key] = size
        self.freq[key] = 1
        self.order[key] = self._counter
        self._counter += 1
        self.current_size += size

    def _evict_until_fits(self, size: int) -> None:
        while self.current_size + size > self.capacity and self.cache:
            # Find min frequency, break ties by insertion order
            victim = min(
                self.cache,
                key=lambda k: (self.freq[k], self.order[k]),
            )
            self.current_size -= self.cache[victim]
            del self.cache[victim]
            del self.freq[victim]
            del self.order[victim]
            self.stats.evictions += 1


# ---------------------------------------------------------------------------
# 3. ARC — Adaptive Replacement Cache (Megiddo & Modha, FAST '03)
# ---------------------------------------------------------------------------
class ARC(CachePolicy):
    """Adaptive Replacement Cache.

    Maintains four lists:
      T1 — recent (seen once), most recently used at tail
      T2 — frequent (seen 2+), most recently used at tail
      B1 — ghost list for T1 evictions (metadata only)
      B2 — ghost list for T2 evictions (metadata only)

    Adaptive parameter p controls the split between T1 and T2.
    """

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self.p = 0  # target size for T1 in bytes
        self.t1: OrderedDict[str, int] = OrderedDict()  # key -> size
        self.t2: OrderedDict[str, int] = OrderedDict()  # key -> size
        self.b1: OrderedDict[str, int] = OrderedDict()  # key -> size (ghost)
        self.b2: OrderedDict[str, int] = OrderedDict()  # key -> size (ghost)
        self.t1_size = 0
        self.t2_size = 0

    @property
    def current_size(self):
        return self.t1_size + self.t2_size

    @current_size.setter
    def current_size(self, val):
        pass  # managed internally

    def access(self, key: str, size: int) -> bool:
        if size > self.capacity:
            self.stats.misses += 1
            self.stats.byte_misses += size
            return False

        # Case 1: key in T1 or T2 (cache hit)
        if key in self.t1:
            old_size = self.t1.pop(key)
            self.t1_size -= old_size
            self.t2[key] = size
            self.t2_size += size
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        if key in self.t2:
            self.t2.move_to_end(key)
            # Update size if changed (shouldn't normally, but be safe)
            old_size = self.t2[key]
            self.t2_size += size - old_size
            self.t2[key] = size
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Cache miss
        self.stats.misses += 1
        self.stats.byte_misses += size

        # Case 2: key in B1 (ghost hit on recency list)
        if key in self.b1:
            ghost_size = self.b1[key]
            # Adapt: increase p (favor recency)
            delta = max(1, (self._b2_total() // max(self._b1_total(), 1)) * ghost_size)
            self.p = min(self.p + delta, self.capacity)
            del self.b1[key]
            self._replace(key, size, in_b2=False)
            self.t2[key] = size
            self.t2_size += size
            return False

        # Case 3: key in B2 (ghost hit on frequency list)
        if key in self.b2:
            ghost_size = self.b2[key]
            # Adapt: decrease p (favor frequency)
            delta = max(1, (self._b1_total() // max(self._b2_total(), 1)) * ghost_size)
            self.p = max(self.p - delta, 0)
            del self.b2[key]
            self._replace(key, size, in_b2=True)
            self.t2[key] = size
            self.t2_size += size
            return False

        # Case 4: key not in T1, T2, B1, B2
        # Check if we need to make room in directory (ghost lists)
        b1_total = self._b1_total()
        b2_total = self._b2_total()
        t1t2 = self.t1_size + self.t2_size

        if b1_total + t1t2 >= self.capacity:
            if b1_total > 0 and self.b1:
                self.b1.popitem(last=False)
            elif self.t1:
                _, evicted_size = self.t1.popitem(last=False)
                self.t1_size -= evicted_size
                self.stats.evictions += 1
        elif t1t2 + b1_total + b2_total >= self.capacity:
            if self.b2:
                self.b2.popitem(last=False)

        # Make room in cache
        self._replace(key, size, in_b2=False)
        self.t1[key] = size
        self.t1_size += size
        return False

    def _replace(self, key: str, size: int, in_b2: bool) -> None:
        """Evict from T1 or T2 until size fits."""
        while self.t1_size + self.t2_size + size > self.capacity:
            if self.t1 and (self.t1_size > self.p or (in_b2 and self.t1_size == self.p)):
                evicted_key, evicted_size = self.t1.popitem(last=False)
                self.t1_size -= evicted_size
                self.b1[evicted_key] = evicted_size
                self.stats.evictions += 1
            elif self.t2:
                evicted_key, evicted_size = self.t2.popitem(last=False)
                self.t2_size -= evicted_size
                self.b2[evicted_key] = evicted_size
                self.stats.evictions += 1
            else:
                break

        # Trim ghost lists to capacity
        while self._b1_total() > self.capacity and self.b1:
            self.b1.popitem(last=False)
        while self._b2_total() > self.capacity and self.b2:
            self.b2.popitem(last=False)

    def _b1_total(self) -> int:
        return sum(self.b1.values()) if self.b1 else 0

    def _b2_total(self) -> int:
        return sum(self.b2.values()) if self.b2 else 0

    def _lookup(self, key: str) -> bool:
        return False  # not used; access() handles everything

    def _admit(self, key: str, size: int) -> None:
        pass  # not used

    def _evict_until_fits(self, size: int) -> None:
        pass  # not used


# ---------------------------------------------------------------------------
# 4. S3FIFO — Small-Small-Small FIFO (Yang et al., SOSP '23)
# ---------------------------------------------------------------------------
class S3FIFO(CachePolicy):
    """S3-FIFO: Small FIFO (10%) + Main FIFO (90%) + Ghost FIFO.

    Objects enter Small. On eviction from Small, if freq >= 1, promote to Main.
    Otherwise, insert into Ghost. On ghost hit, next insertion goes to Main.
    """

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        small_frac = 0.10
        self.small_cap = max(int(capacity_bytes * small_frac), 1)
        self.main_cap = capacity_bytes - self.small_cap

        # Small FIFO: list of (key, size), dict for lookup
        self.small_q: list[tuple[str, int]] = []
        self.small_set: dict[str, int] = {}  # key -> freq (0 or 1+)
        self.small_size = 0

        # Main FIFO: list of (key, size), dict for lookup
        self.main_q: list[tuple[str, int]] = []
        self.main_set: dict[str, int] = {}  # key -> freq
        self.main_size = 0

        # Ghost set (bounded, metadata only)
        self.ghost: OrderedDict[str, None] = OrderedDict()
        self.ghost_cap = max(n_objects_from_bytes(capacity_bytes), 1000)

        # Track sizes for lookup
        self.sizes: dict[str, int] = {}  # key -> size

    def access(self, key: str, size: int) -> bool:
        if size > self.capacity:
            self.stats.misses += 1
            self.stats.byte_misses += size
            return False

        # Hit in small
        if key in self.small_set:
            self.small_set[key] = min(self.small_set[key] + 1, 3)
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Hit in main
        if key in self.main_set:
            self.main_set[key] = min(self.main_set[key] + 1, 3)
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Miss
        self.stats.misses += 1
        self.stats.byte_misses += size

        # Check ghost: if in ghost, insert directly to main
        if key in self.ghost:
            del self.ghost[key]
            self._evict_main_until_fits(size)
            self.main_q.append((key, size))
            self.main_set[key] = 0
            self.main_size += size
            self.sizes[key] = size
        else:
            # Insert into small
            self._evict_small_until_fits(size)
            self.small_q.append((key, size))
            self.small_set[key] = 0
            self.small_size += size
            self.sizes[key] = size

        self.current_size = self.small_size + self.main_size
        return False

    def _evict_small_until_fits(self, size: int) -> None:
        while self.small_size + size > self.small_cap and self.small_q:
            evicted_key, evicted_size = self.small_q.pop(0)
            if evicted_key not in self.small_set:
                continue  # already removed
            freq = self.small_set.pop(evicted_key)
            self.small_size -= evicted_size
            self.stats.evictions += 1

            if freq >= 1:
                # Promote to main
                self._evict_main_until_fits(evicted_size)
                self.main_q.append((evicted_key, evicted_size))
                self.main_set[evicted_key] = 0
                self.main_size += evicted_size
            else:
                # Demote to ghost
                self.ghost[evicted_key] = None
                if len(self.ghost) > self.ghost_cap:
                    self.ghost.popitem(last=False)
                if evicted_key in self.sizes:
                    del self.sizes[evicted_key]

    def _evict_main_until_fits(self, size: int) -> None:
        while self.main_size + size > self.main_cap and self.main_q:
            evicted_key, evicted_size = self.main_q.pop(0)
            if evicted_key not in self.main_set:
                continue
            freq = self.main_set[evicted_key]
            if freq >= 1:
                # Re-insert with decremented frequency (second chance)
                self.main_set[evicted_key] = freq - 1
                self.main_q.append((evicted_key, evicted_size))
            else:
                del self.main_set[evicted_key]
                self.main_size -= evicted_size
                self.stats.evictions += 1
                if evicted_key in self.sizes:
                    del self.sizes[evicted_key]

    def _lookup(self, key: str) -> bool:
        return False  # not used

    def _admit(self, key: str, size: int) -> None:
        pass  # not used

    def _evict_until_fits(self, size: int) -> None:
        pass  # not used


def n_objects_from_bytes(capacity_bytes: int) -> int:
    """Estimate number of objects that fit in capacity (for ghost list sizing)."""
    avg_size = 10 * 1024  # 10KB average
    return capacity_bytes // avg_size


# ---------------------------------------------------------------------------
# 5. WTinyLFU — Window Tiny LFU (Einziger et al., TOS '17)
# ---------------------------------------------------------------------------
class _CountMinSketch:
    """Count-Min Sketch for frequency estimation."""

    def __init__(self, width: int = 2048, depth: int = 4, seed: int = 42):
        self.width = width
        self.depth = depth
        self.table = [[0] * width for _ in range(depth)]
        self.total = 0
        self.reset_threshold = width * 10  # reset when total exceeds this
        # Hash seeds
        import random as _rng
        r = _rng.Random(seed)
        self.seeds = [r.randint(0, 2**31) for _ in range(depth)]

    def _hash(self, key: str, i: int) -> int:
        import hashlib

        digest = hashlib.blake2b(
            f"{self.seeds[i]}::{key}".encode("utf-8"),
            digest_size=8,
        ).digest()
        return int.from_bytes(digest, byteorder="big", signed=False) % self.width

    def increment(self, key: str) -> None:
        self.total += 1
        for i in range(self.depth):
            idx = self._hash(key, i)
            self.table[i][idx] += 1
        # Periodic halving (aging)
        if self.total >= self.reset_threshold:
            self._reset()

    def estimate(self, key: str) -> int:
        return min(self.table[i][self._hash(key, i)] for i in range(self.depth))

    def _reset(self):
        """Halve all counters (aging / freshness mechanism)."""
        for i in range(self.depth):
            for j in range(self.width):
                self.table[i][j] //= 2
        self.total //= 2


class WTinyLFU(CachePolicy):
    """Window TinyLFU.

    Window cache (1% capacity, LRU) + Main cache (99% capacity).
    Main cache is segmented LRU: probation (20% of main) + protected (80% of main).
    Admission from window to main uses TinyLFU filter (Count-Min Sketch):
    candidate (from window) must have higher estimated frequency than victim
    (from probation) to be admitted.
    """

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self.window_cap = max(int(capacity_bytes * 0.01), 1)
        main_cap = capacity_bytes - self.window_cap
        self.probation_cap = max(int(main_cap * 0.20), 1)
        self.protected_cap = main_cap - self.probation_cap

        self.window: OrderedDict[str, int] = OrderedDict()  # key -> size
        self.probation: OrderedDict[str, int] = OrderedDict()  # key -> size
        self.protected: OrderedDict[str, int] = OrderedDict()  # key -> size

        self.window_size = 0
        self.probation_size = 0
        self.protected_size = 0

        self.sketch = _CountMinSketch(width=max(capacity_bytes // 1024, 256))

    def access(self, key: str, size: int) -> bool:
        if size > self.capacity:
            self.stats.misses += 1
            self.stats.byte_misses += size
            return False

        self.sketch.increment(key)

        # Hit in window
        if key in self.window:
            self.window.move_to_end(key)
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Hit in protected
        if key in self.protected:
            self.protected.move_to_end(key)
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Hit in probation -> promote to protected
        if key in self.probation:
            old_size = self.probation.pop(key)
            self.probation_size -= old_size
            # Make room in protected
            while self.protected_size + size > self.protected_cap and self.protected:
                demoted_key, demoted_size = self.protected.popitem(last=False)
                self.protected_size -= demoted_size
                # Demote to probation
                self.probation[demoted_key] = demoted_size
                self.probation_size += demoted_size
            self.protected[key] = size
            self.protected_size += size
            self.stats.hits += 1
            self.stats.byte_hits += size
            return True

        # Miss
        self.stats.misses += 1
        self.stats.byte_misses += size

        # Insert into window
        # Evict from window if needed
        evicted_from_window: list[tuple[str, int]] = []
        while self.window_size + size > self.window_cap and self.window:
            ek, es = self.window.popitem(last=False)
            self.window_size -= es
            evicted_from_window.append((ek, es))

        self.window[key] = size
        self.window_size += size

        # Try to admit evicted window items into main (probation)
        for ek, es in evicted_from_window:
            candidate_freq = self.sketch.estimate(ek)

            # Find victim in probation (LRU end = front)
            if self.probation and self.probation_size + es > self.probation_cap:
                victim_key = next(iter(self.probation))
                victim_freq = self.sketch.estimate(victim_key)

                if candidate_freq > victim_freq:
                    # Admit candidate, evict victim
                    victim_size = self.probation.pop(victim_key)
                    self.probation_size -= victim_size
                    self.stats.evictions += 1
                    # Evict more if needed
                    while self.probation_size + es > self.probation_cap and self.probation:
                        vk, vs = self.probation.popitem(last=False)
                        self.probation_size -= vs
                        self.stats.evictions += 1
                    self.probation[ek] = es
                    self.probation_size += es
                else:
                    # Reject candidate (victim stays)
                    self.stats.evictions += 1
            else:
                # Room in probation, just add
                self.probation[ek] = es
                self.probation_size += es

        self.current_size = self.window_size + self.probation_size + self.protected_size
        return False

    def _lookup(self, key: str) -> bool:
        return False  # not used

    def _admit(self, key: str, size: int) -> None:
        pass  # not used

    def _evict_until_fits(self, size: int) -> None:
        pass  # not used


# ---------------------------------------------------------------------------
# 6. GDSF — Greedy Dual Size Frequency
# ---------------------------------------------------------------------------
class GDSF(CachePolicy):
    """Greedy Dual Size Frequency.

    Priority = (frequency * cost) / size + clock.
    Evict the item with minimum priority. Clock is set to the priority
    of the last evicted item (inflation factor).
    Cost = 1 for all objects (latency-based cost could be added later).
    """

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self.cache: dict[str, int] = {}  # key -> size
        self.freq: dict[str, int] = {}  # key -> frequency
        self.priority: dict[str, float] = {}  # key -> priority value
        self.clock = 0.0
        self.heap: list[tuple[float, str]] = []  # (priority, key)

    def _compute_priority(self, key: str, size: int, freq: int) -> float:
        cost = 1.0  # unit cost; could be latency
        effective_size = max(size, 1)
        return (freq * cost) / effective_size + self.clock

    def _lookup(self, key: str) -> bool:
        if key in self.cache:
            self.freq[key] += 1
            new_priority = self._compute_priority(key, self.cache[key], self.freq[key])
            self.priority[key] = new_priority
            heapq.heappush(self.heap, (new_priority, key))
            return True
        return False

    def _admit(self, key: str, size: int) -> None:
        self.cache[key] = size
        self.freq[key] = 1
        priority = self._compute_priority(key, size, 1)
        self.priority[key] = priority
        heapq.heappush(self.heap, (priority, key))
        self.current_size += size

    def _evict_until_fits(self, size: int) -> None:
        while self.current_size + size > self.capacity and self.cache:
            # Pop from heap, skip stale entries
            while self.heap:
                pri, victim = heapq.heappop(self.heap)
                if victim in self.cache and abs(pri - self.priority[victim]) < 1e-12:
                    # Valid entry
                    self.clock = pri
                    self.current_size -= self.cache[victim]
                    del self.cache[victim]
                    del self.freq[victim]
                    del self.priority[victim]
                    self.stats.evictions += 1
                    break
            else:
                break  # heap exhausted
