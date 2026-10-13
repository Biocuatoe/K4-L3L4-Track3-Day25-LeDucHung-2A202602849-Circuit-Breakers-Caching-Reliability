"""Part G — a semantic response cache that is safe, fresh, and keeps FAQ answers up in an outage.

* ``SemanticCache``: lookup by embedding similarity *within a scope* (prompt
  version; personal questions never), TTL + a stale window, invalidation by
  source document, bounded size (LRU).
* ``CachingClient``: wraps your ResilientClient. A fresh hit answers without
  calling any provider; a miss goes to the providers and the answer is stored;
  when the providers give up, a *stale* answer beats no answer (fallback
  ladder, rung 3: "cached response").

Tests: tests/test_cache.py, then `make cache` (tape C1).

Lifetime of an entry (age = now - stored_at):

    0 ......... ttl_s ................ ttl_s + max_stale_s ......
    |   fresh   |  stale: only if no provider answers  |  expired: drop it

Only FAQ calls carry ``call.request``; every other call has ``request=None``
and must go straight to the inner client.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from gameday_lab.sim.contracts import (
    Action,
    Answer,
    Attempt,
    BaseClient,
    CallContext,
    GiveUp,
    ProviderError,
    Request,
    Serve,
)


def cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """PROVIDED. Cosine similarity: 1.0 = same direction (high = strict threshold)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Entry:
    embedding: tuple[float, ...]
    answer: Answer
    stored_at: float
    last_used: float


@dataclass(frozen=True)
class CacheHit:
    answer: Answer
    similarity: float
    age_s: float
    fresh: bool  # age_s <= ttl_s; a stale hit may only be served when no provider can answer


class SemanticCache:
    def __init__(self, similarity_threshold: float = 0.9, ttl_s: float = 60.0, max_stale_s: float = 600.0,
                 max_entries: int = 500) -> None:
        """PROVIDED: reads the `cache:` block of configs/gameday.yaml."""
        self.similarity_threshold = similarity_threshold
        self.ttl_s = ttl_s
        self.max_stale_s = max_stale_s
        self.max_entries = max_entries
        self.entries: list[Entry] = []

    def lookup(self, req: Request, now: float) -> CacheHit | None:
        """The best usable entry for ``req``, or None.

        * personal questions (``req.personal``) are not in the allowlist -> None
        * expired entries (age > ttl_s + max_stale_s) are dropped
        * scope: only entries whose ``answer.prompt_version == req.prompt_version``
        * best = highest cosine similarity, which must reach ``similarity_threshold``
        """
        if req.personal:
            return None
        horizon = self.ttl_s + self.max_stale_s
        self.entries = [e for e in self.entries if now - e.stored_at <= horizon]
        best = self._best(req)
        if best is None:
            return None
        entry, sim = best
        entry.last_used = now
        age = now - entry.stored_at
        return CacheHit(entry.answer, sim, age, fresh=age <= self.ttl_s)

    def _best(self, req: Request) -> tuple[Entry, float] | None:
        """Most similar in-scope entry at or above the threshold (embeddings of another size never match)."""
        best: tuple[Entry, float] | None = None
        for e in self.entries:
            if e.answer.prompt_version != req.prompt_version or len(e.embedding) != len(req.embedding):
                continue
            sim = cosine(req.embedding, e.embedding)
            if sim >= self.similarity_threshold and (best is None or sim > best[1]):
                best = (e, sim)
        return best

    def store(self, req: Request, answer: Answer, now: float) -> None:
        """Remember ``answer`` for ``req``; same question -> refresh, never pile up duplicates; LRU-bounded."""
        if req.personal:
            return
        same = self._best(Request(req.text, req.user_id, False, answer.prompt_version, req.embedding))
        if same is not None:
            entry = same[0]
            entry.embedding, entry.answer, entry.stored_at, entry.last_used = req.embedding, answer, now, now
            return
        self.entries.append(Entry(req.embedding, answer, now, now))
        if len(self.entries) > self.max_entries:
            self.entries.remove(min(self.entries, key=lambda e: e.last_used))

    def invalidate(self, source: str, now: float) -> int:
        """Drop every entry whose ``answer.sources`` contains ``source``; return how many."""
        kept = [e for e in self.entries if source not in e.answer.sources]
        dropped = len(self.entries) - len(kept)
        self.entries = kept
        return dropped


class CachingClient(BaseClient):
    name = "cached"

    def __init__(self, inner: BaseClient, cache: SemanticCache) -> None:
        """PROVIDED. ``inner`` is your ResilientClient (see factory.build_client("cached"))."""
        self.inner = inner
        self.cache = cache

    def on_cancel(self, call: CallContext, tag: Any, now: float) -> None:
        """PROVIDED."""
        self.inner.on_cancel(call, tag, now)

    # ------------------------------------------------------------------ TODO
    def start(self, call: CallContext, now: float) -> Action:
        """A fresh hit is served without calling any provider; anything else goes to the inner client."""
        if call.request is not None:
            hit = self.cache.lookup(call.request, now)
            if hit is not None and hit.fresh:
                return Serve(hit.answer)
        return self._or_stale(call, self.inner.start(call, now), now)

    def on_success(self, attempt: Attempt, now: float, latency_s: float) -> None:
        """Inner client first (its breaker needs the result), then remember the answer."""
        self.inner.on_success(attempt, now, latency_s)
        call = attempt.call
        if call.request is not None and call.answer is not None:
            self.cache.store(call.request, call.answer, now)

    def on_error(self, attempt: Attempt, err: ProviderError, now: float) -> Action:
        return self._or_stale(attempt.call, self.inner.on_error(attempt, err, now), now)

    def on_content_update(self, source: str, now: float) -> None:
        """A document changed (webhook): drop the answers grounded on it."""
        self.cache.invalidate(source, now)
        self.inner.on_content_update(source, now)

    def _or_stale(self, call: CallContext, action: Action, now: float) -> Action:
        """Stale-if-error: when the providers give up, any still-valid cached answer beats no answer.

        The cache is looked up again *now*, so an invalidation that happened while the call was in flight is honoured.
        """
        if isinstance(action, GiveUp) and call.request is not None:
            hit = self.cache.lookup(call.request, now)
            if hit is not None:
                return Serve(hit.answer, stale=not hit.fresh)
        return action
