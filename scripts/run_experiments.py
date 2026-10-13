"""Reproduce the experiments of report sections 3 and 8 (isolated overrides — the real code and config are untouched).

    python scripts/run_experiments.py            # -> reports/experiments.json (+ a summary on stdout)

Every experiment overrides settings *in memory* (client:/cache: dicts, or a ClientNoCapabilityFilter subclass that
lives only in this file); nothing in src/ or configs/ is modified.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # run without pip install

import copy
import dataclasses
import json
from typing import Any

from gameday_lab.cache import CacheHit, CachingClient, SemanticCache, cosine
from gameday_lab.client import ResilientClient
from gameday_lab.sim.config import LabConfig, load_config
from gameday_lab.sim.contracts import Answer, Request
from gameday_lab.sim.engine import evaluate_checks, run_scenario
from gameday_lab.sim.faq import INTENTS, FaqCatalog

SEED = 25
CLIENT_RNG_SEED = 1  # what factory.build_client() / the grader use for the client's jitter RNG
CLIENT_KEYS = ["availability", "latency_p95_s", "amplification", "retry_ratio", "recovery_s",
               "primary_share_after_restore", "cost_per_good_turn", "give_up_reasons", "attempts_by_provider",
               "errors_by_code", "incompatible_routes"]
CACHE_KEYS = ["availability", "faq_availability", "cache_hit_ratio", "stale_served", "wrong_answers",
              "wrong_answers_by_reason", "outdated_answers", "cost_per_good_turn"]


class ClientNoCapabilityFilter(ResilientClient):
    """Experiment 3 only: the ladder ignores ``supports_tools`` (the bug the capability filter prevents)."""

    def ladder(self, task: str) -> list[str]:
        return list(self.order)


class CacheIgnoringPersonal(SemanticCache):
    """Ablation: the 'personal questions are never cached' rule removed."""

    def lookup(self, req: Request, now: float) -> CacheHit | None:
        return super().lookup(dataclasses.replace(req, personal=False), now)

    def store(self, req: Request, answer: Answer, now: float) -> None:
        super().store(dataclasses.replace(req, personal=False), answer, now)


class CacheIgnoringPromptVersion(SemanticCache):
    """Ablation: entries are no longer scoped by prompt version."""

    def lookup(self, req: Request, now: float) -> CacheHit | None:
        return super().lookup(dataclasses.replace(req, prompt_version=self._any_version(req)), now)

    def _any_version(self, req: Request) -> str:
        best = max(((cosine(req.embedding, e.embedding), e.answer.prompt_version) for e in self.entries
                    if len(e.embedding) == len(req.embedding)), default=(0.0, req.prompt_version))
        return best[1]


class CachingClientIgnoringWebhook(CachingClient):
    """Ablation: the CMS webhook is ignored."""

    def on_content_update(self, source: str, now: float) -> None:
        return None


def with_client(cfg: LabConfig, **overrides: Any) -> LabConfig:
    client = copy.deepcopy(cfg.client)
    for k, v in overrides.items():
        if k.startswith("breaker."):
            client.setdefault("breaker", {})[k.split(".", 1)[1]] = v
        else:
            client[k] = v
    return dataclasses.replace(cfg, client=client)


def run_client(cfg: LabConfig, key: str, cls: type[ResilientClient] = ResilientClient, seed: int = SEED) -> dict[str, Any]:
    client = cls(cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=CLIENT_RNG_SEED)
    m = run_scenario(cfg, key, client, seed).metrics()
    out = {k: m[k] for k in CLIENT_KEYS}
    out["checks"] = evaluate_checks(m, cfg.scenarios[key].checks)
    return out


def run_cache(cfg: LabConfig, seed: int = SEED, cache_cls: type[SemanticCache] = SemanticCache,
              client_cls: type[CachingClient] = CachingClient, **cache_overrides: Any) -> dict[str, Any]:
    settings = {**cfg.cache, **cache_overrides}
    client = client_cls(ResilientClient(cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=CLIENT_RNG_SEED),
                        cache_cls(**settings))
    m = run_scenario(cfg, "C1_faq_outage", client, seed).metrics()
    out = {"settings": settings, **{k: m[k] for k in CACHE_KEYS}}
    out["checks"] = evaluate_checks(m, cfg.scenarios["C1_faq_outage"].checks)
    return out


def main() -> None:
    cfg = load_config("configs/gameday.yaml", "configs/scenarios.yaml")
    cache_cfg = load_config("configs/gameday.yaml", "configs/scenarios_cache.yaml")
    res: dict[str, Any] = {"seed": SEED}

    # --- experiment 1: retry budget vs a breaker that never trips --------------------------------------------
    broken = {"breaker.min_calls": 1_000_000_000, "max_attempts_per_provider": 5}
    no_budget = {"retry_budget_ratio": 100, "retry_budget_max_tokens": 1.0e9, "retry_budget_min_per_s": 1.0e6}
    exp1: dict[str, Any] = {}
    for key in ("G2_overload_storm", "G3_brownout"):
        exp1[key] = {
            "final_config": run_client(cfg, key),
            "broken_breaker_with_budget": run_client(with_client(cfg, **broken), key),
            "broken_breaker_without_budget": run_client(with_client(cfg, **broken, **no_budget), key),
        }
    res["exp1_budget_vs_broken_breaker"] = exp1

    # --- experiment 2: attempt_timeout_s = 30 ---------------------------------------------------------------
    res["exp2_attempt_timeout_30"] = {
        key: {"timeout_8": run_client(cfg, key), "timeout_30": run_client(with_client(cfg, attempt_timeout_s=30.0), key)}
        for key in ("G6_provider_outage", "G4_slow_region")
    }

    # --- experiment 3: no capability filtering --------------------------------------------------------------
    res["exp3_no_capability_filter"] = {
        "with_filter": run_client(cfg, "G6_provider_outage"),
        "without_filter": run_client(cfg, "G6_provider_outage", ClientNoCapabilityFilter),
    }

    # --- sensitivity of the client: parameters in report section 2 (one parameter at a time) -------------------
    sweeps: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {
        "attempt_timeout_s": ((4.0, 8.0, 15.0), ("G2_overload_storm", "G4_slow_region", "G6_provider_outage")),
        "max_attempts_per_provider": ((1, 2, 4), ("G2_overload_storm", "G3_brownout")),
        "retry_budget_ratio": ((0.0, 0.1, 0.5), ("G2_overload_storm", "G3_brownout")),
        "breaker.failure_rate_threshold": ((0.25, 0.5, 0.8), ("G2_overload_storm", "G3_brownout", "G6_provider_outage")),
        "breaker.slow_call_s": ((2.0, 3.0, 5.0, 1.0e9), ("G4_slow_region", "G2_overload_storm")),
        "breaker.open_duration_s": ((2.0, 10.0, 30.0), ("G2_overload_storm", "G6_provider_outage")),
        "breaker.half_open_max_probes": ((1, 2, 10), ("G2_overload_storm", "G6_provider_outage")),
    }
    sens: dict[str, Any] = {}
    for param, (values, keys) in sweeps.items():
        sens[param] = {key: {str(v): run_client(with_client(cfg, **{param: v}), key) for v in values} for key in keys}
    window = {"10/5": (10, 5), "20/10": (20, 10), "50/25": (50, 25)}
    sens["breaker.window_size/min_calls"] = {
        key: {name: run_client(with_client(cfg, **{"breaker.window_size": w, "breaker.min_calls": m}), key)
              for name, (w, m) in window.items()}
        for key in ("G2_overload_storm", "G3_brownout", "G6_provider_outage")
    }
    res["client_sensitivity"] = sens

    # --- does the breaker ever trip on the 30% brown-out (G3)? ------------------------------------------------
    probe = ResilientClient(cfg.provider_infos(), cfg.fallback_order, cfg.client, seed=CLIENT_RNG_SEED)
    run_scenario(cfg, "G3_brownout", probe, SEED)
    res["g3_breaker_transitions"] = {name: [f"{t.frm.value}->{t.to.value}:{t.reason}@{t.t:.1f}" for t in b.transitions]
                                     for name, b in probe.breakers.items()}

    # --- section 8 experiments ------------------------------------------------------------------------------
    res["cache_threshold"] = {str(t): run_cache(cache_cfg, similarity_threshold=t) for t in (0.80, 0.92, 0.97)}
    res["cache_ttl"] = {str(t): run_cache(cache_cfg, ttl_s=t) for t in (30, 60, 300)}
    res["cache_stale"] = {str(s): run_cache(cache_cfg, max_stale_s=s) for s in (0, 120, 300)}
    res["cache_starter_config"] = run_cache(cache_cfg, similarity_threshold=0.80, ttl_s=600, max_stale_s=0)
    res["cache_ablations"] = {
        "no_prompt_version_scope": run_cache(cache_cfg, cache_cls=CacheIgnoringPromptVersion),
        "ignore_webhook": run_cache(cache_cfg, client_cls=CachingClientIgnoringWebhook),
        "cache_personal_answers": run_cache(cache_cfg, cache_cls=CacheIgnoringPersonal),
    }
    catalog = FaqCatalog()
    emb = [(i.key, catalog.embed(t)) for i in INTENTS if i.source is not None for t in i.texts]
    same = [(cosine(a[1], b[1]), a[0]) for n, a in enumerate(emb) for b in emb[n + 1:] if a[0] == b[0]]
    diff = [(cosine(a[1], b[1]), f"{a[0]} vs {b[0]}") for n, a in enumerate(emb) for b in emb[n + 1:] if a[0] != b[0]]
    res["catalog_similarity"] = {"min_same_intent": min(same), "top_cross_intent": sorted(diff, reverse=True)[:5]}
    res["cache_multi_seed_final"] = {str(s): run_cache(cache_cfg, seed=s) for s in (25, 26, 27)}

    Path("reports").mkdir(exist_ok=True)
    Path("reports/experiments.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
