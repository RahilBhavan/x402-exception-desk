"""Reproducible scenario experiments for exception-queue policies.

The assumptions in this module are inputs, not empirical claims.  They make
the synthetic experiment auditable and easy to replace after practitioner
review.  All policies in a scenario receive the exact same fingerprinted
workload and are judged on the metrics declared below before execution.
"""

from __future__ import annotations

import math
import random
from itertools import product
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .policy import compare_policy_set

POLICY_NAMES = ("fifo", "deadline_first", "value_first", "hybrid")
PREDECLARED_METRICS = (
    "overdue_count",
    "value_weighted_overdue_minutes",
    "p95_resolution_delay_minutes",
    "unfinished_count",
    "total_control_failures",
)

# Synthetic manual-handling assumptions, in minutes. These are deliberately
# explicit so a reviewer can challenge them without changing simulation code.
HANDLING_TIME_ASSUMPTIONS = {
    "evidence_mismatch": {"fast": 6.0, "base": 12.0, "slow": 25.0},
    "timeout_reconciliation": {"fast": 10.0, "base": 20.0, "slow": 45.0},
    "delivery_recovery": {"fast": 4.0, "base": 8.0, "slow": 18.0},
    "refund_investigation": {"fast": 15.0, "base": 30.0, "slow": 60.0},
}


def generate_seeded_workload(
    seed: int,
    *,
    case_count: int = 40,
    duration_multiplier: float = 1.0,
    evidence_delay_minutes: float = 0.0,
    finality_delay_minutes: float = 0.0,
) -> list[dict[str, Any]]:
    """Create a deterministic synthetic day without sampling future state.

    Finality delay applies only to settlement-evidence cases; evidence delay
    applies to every case.  Both move ``actionable_at`` and never opening time
    or deadline, modeling delayed evidence rather than clairvoyant scheduling.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 1:
        raise ValueError("case_count must be a positive integer")
    for label, value in (
        ("duration_multiplier", duration_multiplier),
        ("evidence_delay_minutes", evidence_delay_minutes),
        ("finality_delay_minutes", finality_delay_minutes),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{label} must be a finite non-negative number")

    rng = random.Random(seed)
    kinds = tuple(HANDLING_TIME_ASSUMPTIONS)
    workload = []
    for index in range(case_count):
        kind = kinds[rng.randrange(len(kinds))]
        opened = float(rng.randrange(0, 360))
        sla = float(rng.choice((30, 45, 60, 90, 120)))
        base_duration = HANDLING_TIME_ASSUMPTIONS[kind]["base"]
        # Bounded deterministic variation avoids every case of a type taking
        # exactly the same time while retaining the named base assumption.
        variation = rng.choice((0.8, 1.0, 1.2))
        finality_delay = finality_delay_minutes if kind in {"evidence_mismatch", "timeout_reconciliation"} else 0.0
        workload.append(
            {
                "case_id": f"seed-{seed:06d}-{index:04d}",
                "exception_type": kind,
                "opened_at": opened,
                "deadline": opened + sla,
                "amount_atomic": rng.randrange(1, 501) * 1_000_000,
                "actionable_at": opened + evidence_delay_minutes + finality_delay,
                "duration_minutes": base_duration * variation * duration_multiplier,
                "control_failures": 1 if rng.random() < 0.03 else 0,
            }
        )
    return workload


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)])


def _winner_names(results: Mapping[str, Mapping[str, Any]], metric: str) -> list[str]:
    best = min(float(result[metric]) for result in results.values())
    return sorted(policy for policy, result in results.items() if float(result[metric]) == best)


def run_scenario_sweep(
    *,
    seeds: Iterable[int] = range(100),
    case_count: int = 40,
    staffing_levels: Iterable[int] = (1, 2, 3),
    duration_multipliers: Iterable[float] = (0.5, 1.0, 2.0),
    evidence_delays: Iterable[float] = (0.0, 15.0),
    finality_delays: Iterable[float] = (0.0, 10.0),
    horizon_minutes: float = 480.0,
    sla_window_minutes: float = 30.0,
) -> dict[str, Any]:
    """Run a Cartesian scenario sweep and summarize policy distributions.

    A tied scenario grants each tied policy a fractional win, keeping each
    metric's total win credit equal to the number of scenarios.
    """
    seed_values = tuple(seeds)
    staffing_values = tuple(staffing_levels)
    multiplier_values = tuple(duration_multipliers)
    evidence_values = tuple(evidence_delays)
    finality_values = tuple(finality_delays)
    if not seed_values:
        raise ValueError("at least one seed is required")
    if not staffing_values or not multiplier_values or not evidence_values or not finality_values:
        raise ValueError("scenario dimensions must not be empty")

    scenarios = []
    samples = {
        policy: {metric: [] for metric in PREDECLARED_METRICS}
        for policy in POLICY_NAMES
    }
    win_credits = {
        policy: {metric: 0.0 for metric in PREDECLARED_METRICS}
        for policy in POLICY_NAMES
    }

    dimensions = product(seed_values, staffing_values, multiplier_values, evidence_values, finality_values)
    for seed, staffing, multiplier, evidence_delay, finality_delay in dimensions:
        workload = generate_seeded_workload(
            seed,
            case_count=case_count,
            duration_multiplier=multiplier,
            evidence_delay_minutes=evidence_delay,
            finality_delay_minutes=finality_delay,
        )
        results = compare_policy_set(
            workload,
            horizon=horizon_minutes,
            operator_count=staffing,
            sla_window_minutes=sla_window_minutes,
        )
        fingerprints = {result["workload_fingerprint"] for result in results.values()}
        if len(fingerprints) != 1:
            raise AssertionError("scenario policies did not receive identical workloads")

        winners = {}
        for metric in PREDECLARED_METRICS:
            metric_winners = _winner_names(results, metric)
            winners[metric] = metric_winners
            credit = 1.0 / len(metric_winners)
            for policy in metric_winners:
                win_credits[policy][metric] += credit
            for policy, result in results.items():
                samples[policy][metric].append(float(result[metric]))
        scenarios.append(
            {
                "seed": seed,
                "operator_count": staffing,
                "duration_multiplier": float(multiplier),
                "evidence_delay_minutes": float(evidence_delay),
                "finality_delay_minutes": float(finality_delay),
                "workload_fingerprint": fingerprints.pop(),
                "winners": winners,
                "results": results,
            }
        )

    scenario_count = len(scenarios)
    summary = {}
    for policy in POLICY_NAMES:
        summary[policy] = {}
        for metric in PREDECLARED_METRICS:
            values = samples[policy][metric]
            summary[policy][metric] = {
                "p50": float(median(values)),
                "p95": _nearest_rank(values, 0.95),
                "minimum": min(values),
                "maximum": max(values),
                "win_rate": win_credits[policy][metric] / scenario_count,
            }
    return {
        "handling_time_assumptions": HANDLING_TIME_ASSUMPTIONS,
        "predeclared_metrics": list(PREDECLARED_METRICS),
        "scenario_count": scenario_count,
        "scenarios": scenarios,
        "summary": summary,
    }
