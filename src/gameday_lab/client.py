"""Part C — ResilientClient: compose classification, retry, breaker and fallback.

The simulator calls ``start`` for every logical LLM call, then ``on_success``
or ``on_error`` for every attempt. You answer with ``Send`` (try a provider,
maybe after a delay) or ``GiveUp`` (user gets a static degraded answer).

Tests: tests/test_client.py, then `make compare` (6 incident tapes).

Per-call scratch space lives in ``call.state`` (a dict). Suggested keys:
    "ladder": list[str]  providers this call may use, in order
    "idx":    int        position of the provider we are currently on
    "tries":  int        attempts already made on that provider

Decision table for ``on_error`` (implement it!):

| ErrorKind        | breaker              | then                                                    |
|------------------|----------------------|---------------------------------------------------------|
| CLIENT_ERROR     | release (not health) | GiveUp("client_error") — never retry, never fail over   |
| QUOTA_EXHAUSTED  | release              | cooldown provider for quota_cooldown_s; fail over now   |
| RATE_LIMITED     | release              | cooldown provider until now + retry_after; fail over now|
| OVERLOADED /     | on_failure           | retry SAME provider after backoff.delay(tries) if       |
| SERVER_ERROR /   |                      |   tries < max_attempts_per_provider AND budget allows   |
| TIMEOUT          |                      |   AND it fits the deadline; otherwise fail over         |

Cooldowns are per provider and shared by all calls (other calls must avoid a
rate-limited provider too). When every provider in the ladder is unusable,
you may wait for a *short* (<= 5 s) rate-limit cooldown if it fits the deadline.
"""

from __future__ import annotations

import random
from typing import Any

from gameday_lab.breaker import BreakerState, Permit, SlidingWindowBreaker
from gameday_lab.errors import ErrorKind, classify, counts_toward_breaker, failover_helps, is_retryable
from gameday_lab.retry import FullJitterBackoff, RetryBudget
from gameday_lab.sim.contracts import (
    Action,
    Attempt,
    BaseClient,
    CallContext,
    GiveUp,
    ProviderError,
    ProviderInfo,
    Send,
)

RATE_LIMIT_WAIT_MAX_S = 5.0  # only wait for short (rate-limit) cooldowns, never for quota


class ResilientClient(BaseClient):
    name = "resilient"

    def __init__(
        self,
        providers: dict[str, ProviderInfo],
        fallback_order: list[str] | tuple[str, ...],
        settings: dict[str, Any],
        seed: int = 0,
    ) -> None:
        """PROVIDED: reads the `client:` block of configs/gameday.yaml."""
        self.providers = providers
        self.order = list(fallback_order)
        self.timeout_s = float(settings.get("attempt_timeout_s", 8.0))
        self.max_attempts_per_provider = int(settings.get("max_attempts_per_provider", 2))
        self.min_time_left_s = float(settings.get("min_time_left_s", 1.0))
        self.quota_cooldown_s = float(settings.get("quota_cooldown_s", 300.0))
        self.default_retry_after_s = float(settings.get("default_retry_after_s", 1.0))  # 429 without retry-after
        self.backoff = FullJitterBackoff(
            float(settings.get("backoff_base_s", 0.25)),
            float(settings.get("backoff_cap_s", 4.0)),
            random.Random(seed),
        )
        self.budget = RetryBudget(
            float(settings.get("retry_budget_ratio", 0.1)),
            float(settings.get("retry_budget_min_per_s", 0.5)),
            float(settings.get("retry_budget_max_tokens", 20.0)),
        )
        breaker_cfg = dict(settings.get("breaker", {}))
        self.breakers = {name: SlidingWindowBreaker(name, **breaker_cfg) for name in providers}
        self.cooldown_until: dict[str, float] = {name: 0.0 for name in providers}

    # ------------------------------------------------------------------ provided helper
    def _send(self, call: CallContext, provider: str, now: float, delay: float) -> Action | None:
        """PROVIDED. Build a Send for ``provider`` (after ``delay``), or None if its breaker refuses.

        Takes a breaker permit (carried in ``tag``), and caps the attempt timeout
        so it never runs past the call's deadline. Returns GiveUp("deadline") if
        there is not enough time left for a meaningful attempt.
        """
        permit = self.breakers[provider].allow(now)
        if permit is None:
            return None
        timeout = min(self.timeout_s, call.deadline - (now + delay))
        if timeout < self.min_time_left_s:
            self.breakers[provider].release(permit, now)
            return GiveUp("deadline")
        return Send(provider, timeout_s=timeout, delay_s=delay, tag=permit)

    # ------------------------------------------------------------------ routing
    def ladder(self, task: str) -> list[str]:
        """Fallback order filtered by capability: a "tool" call only goes to tool-capable providers."""
        if task == "tool":
            return [n for n in self.order if self.providers[n].supports_tools]
        return list(self.order)

    def _advance(self, st: dict[str, Any]) -> None:
        """Move to the next provider on the ladder; the failover goes out immediately."""
        st["idx"] += 1
        st["tries"] = 0

    def _route(self, call: CallContext, now: float, delay: float = 0.0) -> Action:
        """Pick the provider for the next attempt (see the module docstring)."""
        st = call.state
        ladder: list[str] = st["ladder"]
        while st["idx"] < len(ladder):
            name = ladder[st["idx"]]
            if self.cooldown_until[name] > now + delay:
                self._advance(st)
                delay = 0.0
                continue
            action = self._send(call, name, now, delay)
            if action is None:  # breaker refuses admission
                self._advance(st)
                delay = 0.0
                continue
            if isinstance(action, Send):
                st["tries"] += 1
            return action
        # Ladder exhausted. A short rate-limit cooldown is worth waiting for if it fits the deadline.
        best: tuple[float, int] | None = None
        for pos, name in enumerate(ladder):
            wait = self.cooldown_until[name] - now
            if (0.0 < wait <= RATE_LIMIT_WAIT_MAX_S and self.breakers[name].state is not BreakerState.OPEN
                    and now + wait + self.min_time_left_s <= call.deadline and (best is None or wait < best[0])):
                best = (wait, pos)
        if best is not None:
            st["idx"], st["tries"] = best[1], 0
            return self._route(call, now, best[0])
        return GiveUp("no_provider_available")

    # ------------------------------------------------------------------ events
    def start(self, call: CallContext, now: float) -> Action:
        self.budget.record_request(now)
        call.state.update(ladder=self.ladder(call.task), idx=0, tries=0)
        return self._route(call, now)

    def on_success(self, attempt: Attempt, now: float, latency_s: float) -> None:
        if isinstance(attempt.tag, Permit):
            self.breakers[attempt.provider].on_success(attempt.tag, now, latency_s)

    def on_error(self, attempt: Attempt, err: ProviderError, now: float) -> Action:
        call, name = attempt.call, attempt.provider
        breaker = self.breakers[name]
        permit = attempt.tag
        st = call.state
        kind = classify(err)

        if counts_toward_breaker(kind):
            if isinstance(permit, Permit):
                breaker.on_failure(permit, now)
        elif isinstance(permit, Permit):
            breaker.release(permit, now)  # says nothing about provider health

        if not failover_helps(kind):  # CLIENT_ERROR: malformed everywhere — never retry, never fail over
            return GiveUp("client_error")

        if kind is ErrorKind.QUOTA_EXHAUSTED:
            self.cooldown_until[name] = max(self.cooldown_until[name], now + self.quota_cooldown_s)
        elif kind is ErrorKind.RATE_LIMITED:
            wait = err.retry_after if err.retry_after is not None else self.default_retry_after_s
            self.cooldown_until[name] = max(self.cooldown_until[name], now + wait)
        elif (is_retryable(kind) and st["tries"] < self.max_attempts_per_provider
              and breaker.state is not BreakerState.OPEN and self.budget.try_acquire_retry(now)):
            return self._route(call, now, self.backoff.delay(st["tries"]))

        self._advance(st)
        return self._route(call, now)

    def on_cancel(self, call: CallContext, tag: Any, now: float) -> None:
        if isinstance(tag, Permit):
            self.breakers[tag.breaker].release(tag, now)
