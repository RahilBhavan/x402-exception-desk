"""Deterministic, non-preemptive operator queue simulations.

The simulator deliberately makes a decision only when the operator becomes
free.  A case that is not yet actionable is not included in that decision,
which prevents a policy from using future availability information.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import heapq
import json
import math
from statistics import median
from typing import Any, Iterable, Mapping, Optional

from .store import parse_timestamp


REQUIRED_FIELDS = (
    "case_id",
    "opened_at",
    "deadline",
    "amount_atomic",
    "actionable_at",
    "duration_minutes",
)
POLICIES = {"fifo", "deadline_first", "value_first", "hybrid"}


def _minutes(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("time values must be numbers, datetimes, or ISO strings")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must include a UTC offset")
        result = value.timestamp() / 60.0
    elif isinstance(value, str):
        result = parse_timestamp(value).timestamp() / 60.0
    else:
        raise ValueError("time values must be numbers, datetimes, or ISO strings")
    if not math.isfinite(result):
        raise ValueError("time values must be finite")
    return result


def _normalise(cases: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalised = []
    seen = set()
    for raw in cases:
        missing = [field for field in REQUIRED_FIELDS if field not in raw]
        if missing:
            raise ValueError(f"case missing required fields: {', '.join(missing)}")
        case_id = str(raw["case_id"])
        if not case_id or case_id in seen:
            raise ValueError(f"case_id must be non-empty and unique: {case_id!r}")
        seen.add(case_id)
        amount = raw["amount_atomic"]
        duration = raw["duration_minutes"]
        failures = raw.get("control_failures", 0)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(f"amount_atomic must be a non-negative integer for {case_id}")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise ValueError(f"duration_minutes must be non-negative for {case_id}")
        if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
            raise ValueError(f"control_failures must be a non-negative integer for {case_id}")
        opened = _minutes(raw["opened_at"])
        actionable = _minutes(raw["actionable_at"])
        normalised.append(
            {
                "case_id": case_id,
                "opened_at": opened,
                "deadline": _minutes(raw["deadline"]),
                "amount_atomic": amount,
                "actionable_at": max(opened, actionable),
                "duration_minutes": float(duration),
                "control_failures": failures,
            }
        )
    return normalised


def workload_fingerprint(cases: Iterable[Mapping[str, Any]]) -> str:
    """Return a stable identity for the workload, independent of input order."""
    payload = sorted(_normalise(cases), key=lambda case: case["case_id"])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _percentile_95(values: list[float]) -> float:
    """Nearest-rank p95, a stable definition suitable for a small corpus."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def simulate_policy(
    cases: Iterable[Mapping[str, Any]],
    policy: str,
    *,
    start_at: Optional[Any] = None,
    horizon: Optional[Any] = None,
    operator_count: int = 1,
    sla_window_minutes: float = 30.0,
) -> dict[str, Any]:
    """Run one non-preemptive queue policy with one or more operators.

    ``horizon`` is a hard observation boundary: work that cannot finish by it
    remains unfinished.  Each completed case represents one manual touch.
    The hybrid policy prioritises cases inside ``sla_window_minutes`` of their
    deadline, then unresolved value, then age.  Only cases actionable at an
    operator's decision time participate, preventing future-data leakage.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    if isinstance(operator_count, bool) or not isinstance(operator_count, int) or operator_count < 1:
        raise ValueError("operator_count must be a positive integer")
    if (
        isinstance(sla_window_minutes, bool)
        or not isinstance(sla_window_minutes, (int, float))
        or not math.isfinite(float(sla_window_minutes))
        or sla_window_minutes < 0
    ):
        raise ValueError("sla_window_minutes must be a finite non-negative number")
    pending = _normalise(cases)
    fingerprint = workload_fingerprint(pending)
    if not pending:
        now = _minutes(start_at) if start_at is not None else 0.0
    else:
        first_open = min(case["opened_at"] for case in pending)
        now = first_open if start_at is None else _minutes(start_at)
    end = math.inf if horizon is None else _minutes(horizon)
    if end < now:
        raise ValueError("horizon must not precede start_at")

    outcomes = []
    operator_heap = [(now, operator_id) for operator_id in range(operator_count)]
    heapq.heapify(operator_heap)
    while pending and operator_heap:
        now, operator_id = heapq.heappop(operator_heap)
        # Only cases that can still finish by the horizon compete; an operator
        # whose remaining time fits no case retires.
        feasible = [case for case in pending
                    if max(now, case["actionable_at"]) + case["duration_minutes"] <= end]
        if not feasible:
            continue
        available = [case for case in feasible if case["actionable_at"] <= now]
        if not available:
            now = min(case["actionable_at"] for case in feasible)
            available = [case for case in feasible if case["actionable_at"] <= now]

        if policy == "fifo":
            chosen = min(available, key=lambda case: (case["opened_at"], case["case_id"]))
        elif policy == "deadline_first":
            chosen = min(
                available,
                key=lambda case: (case["deadline"], case["opened_at"], case["case_id"]),
            )
        elif policy == "value_first":
            chosen = min(
                available,
                key=lambda case: (-case["amount_atomic"], case["deadline"], case["opened_at"], case["case_id"]),
            )
        else:
            chosen = min(
                available,
                key=lambda case: (
                    0 if case["deadline"] - now <= sla_window_minutes else 1,
                    -case["amount_atomic"],
                    case["opened_at"],
                    case["case_id"],
                ),
            )
        completion = now + chosen["duration_minutes"]
        pending.remove(chosen)
        overdue = max(0.0, completion - chosen["deadline"])
        outcomes.append(
            {
                "case_id": chosen["case_id"],
                "started_at": now,
                "completed_at": completion,
                "operator_id": operator_id,
                "resolution_delay_minutes": completion - chosen["opened_at"],
                "overdue_minutes": overdue,
                "amount_atomic": chosen["amount_atomic"],
                "control_failures": chosen["control_failures"],
            }
        )
        heapq.heappush(operator_heap, (completion, operator_id))

    delays = [outcome["resolution_delay_minutes"] for outcome in outcomes]
    return {
        "policy": policy,
        "operator_count": operator_count,
        "sla_window_minutes": float(sla_window_minutes),
        "workload_fingerprint": fingerprint,
        "overdue_count": sum(outcome["overdue_minutes"] > 0 for outcome in outcomes),
        "median_resolution_delay_minutes": median(delays) if delays else 0.0,
        "p95_resolution_delay_minutes": _percentile_95(delays),
        # fsum is exactly rounded; plain sum() changed in Python 3.12 (compensated),
        # which altered released bytes across versions.
        "value_weighted_overdue_minutes": math.fsum(
            outcome["amount_atomic"] * outcome["overdue_minutes"] for outcome in outcomes
        ),
        "unfinished_count": len(pending),
        "unfinished_value_atomic": sum(case["amount_atomic"] for case in pending),
        "unfinished_control_failures": sum(case["control_failures"] for case in pending),
        "touches": len(outcomes),
        "control_failures": sum(outcome["control_failures"] for outcome in outcomes),
        "total_control_failures": sum(outcome["control_failures"] for outcome in outcomes)
        + sum(case["control_failures"] for case in pending),
        "outcomes": outcomes,
    }


def compare_policy_set(
    cases: Iterable[Mapping[str, Any]],
    *,
    policies: Iterable[str] = ("fifo", "deadline_first", "value_first", "hybrid"),
    start_at: Optional[Any] = None,
    horizon: Optional[Any] = None,
    operator_count: int = 1,
    sla_window_minutes: float = 30.0,
) -> dict[str, dict[str, Any]]:
    """Run policies against deep-copied inputs and prove workload identity."""
    workload = deepcopy(list(cases))
    expected = workload_fingerprint(workload)
    results: dict[str, dict[str, Any]] = {}
    for policy in policies:
        result = simulate_policy(
            deepcopy(workload),
            policy,
            start_at=start_at,
            horizon=horizon,
            operator_count=operator_count,
            sla_window_minutes=sla_window_minutes,
        )
        if result["workload_fingerprint"] != expected:
            raise AssertionError("workload identity changed during simulation")
        results[policy] = result
    return results


def compare_policies(
    cases: Iterable[Mapping[str, Any]],
    *,
    deadline_cases: Optional[Iterable[Mapping[str, Any]]] = None,
    start_at: Optional[Any] = None,
    horizon: Optional[Any] = None,
) -> dict[str, dict[str, Any]]:
    """Compare policies after proving that both receive identical workloads."""
    fifo_input = deepcopy(list(cases))
    deadline_input = deepcopy(list(deadline_cases)) if deadline_cases is not None else deepcopy(fifo_input)
    if workload_fingerprint(fifo_input) != workload_fingerprint(deadline_input):
        raise ValueError("policy comparison requires identical workloads")
    fifo = simulate_policy(fifo_input, "fifo", start_at=start_at, horizon=horizon)
    deadline = simulate_policy(deadline_input, "deadline_first", start_at=start_at, horizon=horizon)
    if fifo["workload_fingerprint"] != deadline["workload_fingerprint"]:
        raise AssertionError("workload identity changed during simulation")
    return {"fifo": fifo, "deadline_first": deadline}
