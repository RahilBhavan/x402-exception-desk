"""Pure, deterministic projections for settlement-to-delivery incidents."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .store import InvalidEvent, parse_timestamp, validate_event

BUSINESS_EXCEPTIONS = {
    "authorization_rejected": ("authorization_rejected", True),
    "resource_preparation_failed": ("resource_preparation_failed", True),
    "settlement_failed": ("settlement_failed", True),
    "delivery_failed": ("paid_delivery_failed", True),
    "ingestion_replay_detected": ("delivery_pending", True),
    "duplicate_request_received": ("duplicate_request_suppressed", False),
    "payment_claim_conflicted": ("cross_order_payment_claim_conflict", True),
    "chain_observation_invalidated": ("payment_observation_invalidated", False),
    "refund_submitted_unknown": ("refund_outcome_unknown", False),
}


def _canonical_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Accept either the persisted envelope or the documented fixture envelope."""
    if "type" in event:
        return deepcopy(dict(event))
    if "event_type" not in event:
        return deepcopy(dict(event))  # validation supplies the useful error
    payload = deepcopy(dict(event.get("payload", {})))
    payload.setdefault("order_id", str(event["aggregate_id"]))
    payload["source_event_type"] = str(event["event_type"])
    return {
        "event_id": str(event["event_id"]),
        "type": str(event["event_type"]),
        "occurred_at": str(event.get("occurred_at", event["observed_at"])),
        "observed_at": str(event["observed_at"]),
        "data": payload,
        "sequence": event.get("sequence", 0),
    }


def _body(event: Mapping[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in event.items() if k not in {"event_id", "type", "occurred_at", "observed_at", "data"}}
    body.update(event.get("data", {}))
    return body


def _kind(event: Mapping[str, Any]) -> str:
    return str(event["type"]).strip().lower().replace("-", "_").replace(".", "_")


def _exception(state: dict[str, Any], event: Mapping[str, Any], kind: str,
               subject_id: str | None, detail: str) -> None:
    exception_id = f"{kind}:{event['event_id']}"
    state["exceptions"][exception_id] = {
        "exception_id": exception_id,
        "type": kind,
        "subject_id": subject_id,
        "source_event_id": event["event_id"],
        "detail": detail,
        "status": "actionable",
    }


def initial_state() -> dict[str, Any]:
    return {
        "orders": {}, "payment_attempts": {}, "chain_observations": {},
        "fulfillments": {}, "refunds": {}, "exceptions": {},
        "evidence_claims": {}, "applied_event_ids": [], "business_events": [],
    }


def reduce_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Project events in canonical evidence-availability order.

    Identical duplicate IDs are ignored, making replay idempotent; reusing an
    ID with different content is rejected, as in the event store.  All amounts remain
    integers in atomic units; invalid control transitions open an exception and
    do not mutate the protected balance or entitlement state.
    """
    materialized = [_canonical_event(event) for event in events]
    for event in materialized:
        validate_event(event)
    materialized.sort(key=lambda e: (
        parse_timestamp(e["observed_at"]), e.get("sequence", 0),
        parse_timestamp(e.get("occurred_at", e["observed_at"])), e["event_id"]
    ))
    state = initial_state()
    seen: dict[str, str] = {}
    for event in materialized:
        content = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if event["event_id"] in seen:
            if seen[event["event_id"]] != content:
                raise InvalidEvent(f"event_id {event['event_id']!r} has conflicting content")
            continue
        seen[event["event_id"]] = content
        state["applied_event_ids"].append(event["event_id"])
        _apply(state, event, _kind(event), _body(event))
    return state


def project_case(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the stable business projection produced by the canonical reducer."""
    state = reduce_events(events)
    orders = list(state["orders"].values())
    attempts = list(state["payment_attempts"].values())
    kinds = set(state["business_events"])

    payment = "not_submitted"
    if any(order.get("payment_state") == "conflicted" for order in orders):
        payment = "conflicted"
    elif any(attempt.get("outcome") == "observed" for attempt in attempts):
        payment = "observed"
    elif any(attempt.get("outcome") == "failed" for attempt in attempts):
        payment = "failed"
    elif any(attempt.get("timed_out") for attempt in attempts) or "payment_evidence_received" in kinds:
        payment = "unknown"
    elif "chain_observation_invalidated" in kinds:
        payment = "unknown"

    fulfillment = "not_started"
    fulfillment_states = {item.get("state") for item in state["fulfillments"].values()}
    for candidate in ("delivery_failed", "delivered", "preparation_failed", "prepared", "delivery_pending"):
        if candidate in fulfillment_states:
            fulfillment = candidate
            break

    latest_exception = next(reversed(state["exceptions"].values()), None)
    exception_type = latest_exception.get("type") if latest_exception else None
    actionable = bool(latest_exception and latest_exception.get(
        "actionable", latest_exception.get("status") == "actionable"))
    if "refund_submitted_unknown" in kinds:
        exception_type, actionable = "refund_outcome_unknown", False
    elif "settlement_timed_out" in kinds and payment == "observed" and fulfillment == "prepared":
        exception_type, actionable = "delivery_pending_after_late_settlement", True
    elif payment == "observed" and fulfillment == "prepared" and exception_type is None:
        exception_type, actionable = "delivery_pending", True

    captured = _canonical_capture(state)
    reserved = sum(
        int(refund.get("atomic_amount", 0)) for refund in state["refunds"].values()
        if refund.get("state") in {"approved_reserved", "submitted_unknown"}
    )
    completed = sum(
        int(refund.get("atomic_amount", 0)) for refund in state["refunds"].values()
        if refund.get("state") == "settled"
    )
    return {
        "expected_payment_state": payment,
        "expected_fulfillment_state": fulfillment,
        "expected_exception_type": exception_type,
        "actionable": actionable,
        "expected_financials": {
            "captured_atomic": captured,
            "reserved_refund_atomic": reserved,
            "completed_refund_atomic": completed,
        },
    }


def _canonical_capture(state: Mapping[str, Any], attempt_id: str | None = None) -> int:
    """Sum canonical on-chain amounts, optionally for one payment attempt."""
    return sum(
        int(observation.get("amount_atomic", 0))
        for observation in state["chain_observations"].values()
        if observation.get("canonical", True)
        and (attempt_id is None or str(observation.get("attempt_id")) == attempt_id)
    )


def _apply(state: dict[str, Any], event: Mapping[str, Any], kind: str,
           data: Mapping[str, Any]) -> None:
    source_kind = str(data.get("source_event_type", kind))
    state["business_events"].append(source_kind)
    order_id = str(data.get("order_id", ""))

    # Documented fixture vocabulary is handled here, by the same reducer used
    # for persisted application events.  There is no second projection engine.
    if kind == "order_opened":
        return _apply(state, event, "order_created", {
            **data, "expected_atomic_amount": data["expected_amount_atomic"]
        })
    if kind == "authorization_verified":
        already_paid = any(
            attempt.get("order_id") == order_id and attempt.get("outcome") == "observed"
            for attempt in state["payment_attempts"].values()
        )
        _apply(state, event, "payment_attempt_submitted", data)
        if already_paid:
            _record_business_exception(state, event, "redundant_authorization_blocked", True, order_id)
        return
    if kind == "payment_observed":
        attempt_id = str(data["attempt_id"])
        state["payment_attempts"].setdefault(attempt_id, {
            "attempt_id": attempt_id, "order_id": order_id,
            "outcome": "unknown", "timed_out": False,
        })
        return _apply_chain_observation(state, event, {
            **data, "stage": data.get("finality_stage", "observed")
        })
    if kind == "settlement_timed_out":
        return _apply(state, event, "payment_attempt_timed_out", data)
    if kind == "settlement_failed":
        _apply(state, event, "payment_attempt_failed", data)
        _record_business_exception(state, event, "settlement_failed", True, order_id)
        return
    if kind == "resource_prepared":
        return _apply_fulfillment(state, event, "fulfillment_prepared", data)
    if kind == "delivery_acknowledged":
        return _apply_fulfillment(state, event, "fulfillment_delivered", data)
    if kind == "delivery_failed":
        _apply_fulfillment(state, event, "fulfillment_delivery_failed", data)
        _record_business_exception(state, event, "paid_delivery_failed", True, order_id)
        return
    if kind == "resource_preparation_failed":
        _apply_fulfillment(state, event, "resource_preparation_failed", data)
        _record_business_exception(state, event, "resource_preparation_failed", True, order_id)
        return
    if kind == "chain_observation_invalidated":
        _invalidate_observation(state, event, data)
        _record_business_exception(state, event, "payment_observation_invalidated", False, order_id)
        return
    if kind == "payment_claim_conflicted":
        if order_id in state["orders"]:
            state["orders"][order_id]["payment_state"] = "conflicted"
        _record_business_exception(state, event, "cross_order_payment_claim_conflict", True, order_id)
        return
    if kind == "payment_evidence_received":
        if order_id in state["orders"]:
            state["orders"][order_id]["payment_state"] = "unknown"
        _record_business_exception(state, event, "payment_evidence_mismatch", True, order_id)
        return
    if kind in {"authorization_rejected", "duplicate_request_received", "ingestion_replay_detected"}:
        exc_type, actionable = BUSINESS_EXCEPTIONS[kind]
        _record_business_exception(state, event, exc_type, actionable, order_id)
        return
    if kind == "refund_reservation_rejected":
        _record_business_exception(state, event, "refund_reservation_rejected", True, order_id)
        return
    if kind in {"refund_approved_reserved", "refund_submitted_unknown", "refund_settled"}:
        payment_id = str(data.get("payment_id", ""))
        if not payment_id:
            candidates = [key for key, value in state["payment_attempts"].items()
                          if value.get("order_id") == order_id]
            payment_id = candidates[0] if candidates else ""
        _apply_refund(state, event, kind, {**data, "payment_id": payment_id})
        if kind == "refund_submitted_unknown":
            _record_business_exception(state, event, "refund_outcome_unknown", False, order_id)
        return
    if kind == "order_created":
        order_id = str(data["order_id"])
        amount = data.get("expected_amount", data.get("expected_atomic_amount"))
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise ValueError("order amount must be a non-negative integer in atomic units")
        state["orders"].setdefault(order_id, {
            **dict(data), "order_id": order_id, "expected_atomic_amount": amount,
            "payment_state": "unpaid", "delivery_state": "not_prepared",
        })
        return

    if kind in {"payment_attempt_submitted", "payment_submitted"}:
        attempt_id, order_id = str(data["attempt_id"]), str(data["order_id"])
        state["payment_attempts"].setdefault(attempt_id, {
            **dict(data), "attempt_id": attempt_id, "order_id": order_id,
            "outcome": "unknown", "timed_out": False,
        })
        return

    if kind in {"payment_attempt_timed_out", "payment_timeout"}:
        attempt = state["payment_attempts"].get(str(data["attempt_id"]))
        if attempt:
            attempt["timed_out"] = True  # timeout is explicitly not failure
        return

    if kind in {"payment_attempt_failed", "payment_failed"}:
        attempt = state["payment_attempts"].get(str(data["attempt_id"]))
        if attempt and attempt["outcome"] == "unknown":
            attempt["outcome"] = "failed"
        return

    if kind in {"chain_observed", "chain_observation"}:
        _apply_chain_observation(state, event, data)
        return

    if kind.startswith("fulfillment_") or kind in {"delivery_attempted", "delivered", "delivery_failed"}:
        _apply_fulfillment(state, event, kind, data)
        return

    if kind.startswith("refund_"):
        _apply_refund(state, event, kind, data)
        return

    if kind in {"exception_opened", "exception_closed"}:
        exception_id = str(data.get("exception_id", event["event_id"]))
        record = state["exceptions"].setdefault(exception_id, dict(data))
        record.update({"exception_id": exception_id,
                       "status": "closed" if kind.endswith("closed") else "actionable"})


def _record_business_exception(state: dict[str, Any], event: Mapping[str, Any],
                               kind: str, actionable: bool, subject_id: str) -> None:
    state["exceptions"][str(event["event_id"])] = {
        "exception_id": str(event["event_id"]), "type": kind,
        "subject_id": subject_id, "source_event_id": str(event["event_id"]),
        "status": "actionable" if actionable else "monitoring",
        "actionable": actionable,
    }


def _invalidate_observation(state: dict[str, Any], event: Mapping[str, Any],
                            data: Mapping[str, Any]) -> None:
    tx_ref = str(data.get("transaction_ref", data.get("tx_ref", "")))
    log_index = int(data.get("log_index", 0))
    for observation in state["chain_observations"].values():
        if (str(observation.get("transaction_ref", observation.get("tx_ref", ""))) == tx_ref
                and int(observation.get("log_index", 0)) == log_index):
            observation["canonical"] = False
            observation["invalidated_by"] = event["event_id"]
            attempt = state["payment_attempts"].get(str(observation.get("attempt_id")))
            if attempt:
                attempt["outcome"] = "unknown"
                order = state["orders"].get(attempt.get("order_id"))
                if order:
                    order["payment_state"] = "unknown"
            claim_key = observation.get("claim_key")
            if claim_key:
                state["evidence_claims"].pop(claim_key, None)


def _apply_chain_observation(state: dict[str, Any], event: Mapping[str, Any],
                             data: Mapping[str, Any]) -> None:
    attempt_id = str(data["attempt_id"])
    attempt = state["payment_attempts"].get(attempt_id)
    if not attempt:
        _exception(state, event, "missing_payment_attempt", attempt_id, "observation has no payment attempt")
        return
    claim = (str(data["network"]), str(data.get("transaction_ref", data.get("tx_ref"))), int(data.get("log_index", 0)))
    claim_key = "|".join(map(str, claim))
    order_id = attempt["order_id"]
    owner = state["evidence_claims"].get(claim_key)
    if owner is not None and owner != order_id:
        _exception(state, event, "evidence_claim_conflict", order_id,
                   f"payment evidence is already claimed by order {owner}")
        return
    state["evidence_claims"][claim_key] = order_id
    observation = {**dict(data), "claim_key": claim_key, "event_id": event["event_id"]}
    state["chain_observations"][event["event_id"]] = observation
    if data.get("canonical", True) and data.get("stage", "observed") not in {"removed", "reverted"}:
        attempt["outcome"] = "observed"  # late evidence updates this attempt
        attempt["evidence_claim"] = claim_key
        order = state["orders"].get(order_id)
        if order:
            order["payment_state"] = "observed"


def _apply_fulfillment(state: dict[str, Any], event: Mapping[str, Any], kind: str,
                       data: Mapping[str, Any]) -> None:
    order_id = str(data["order_id"])
    record = state["fulfillments"].setdefault(order_id, {"order_id": order_id, "state": "not_prepared"})
    transitions = {
        "fulfillment_prepared": "prepared", "fulfillment_delivery_pending": "delivery_pending",
        "fulfillment_delivered": "delivered", "delivered": "delivered",
        "fulfillment_delivery_failed": "delivery_failed", "delivery_failed": "delivery_failed",
        "delivery_attempted": "delivery_pending",
        "resource_preparation_failed": "preparation_failed",
    }
    record.update(dict(data))
    record["state"] = transitions.get(kind, record["state"])
    if order_id in state["orders"]:
        state["orders"][order_id]["delivery_state"] = record["state"]


def _apply_refund(state: dict[str, Any], event: Mapping[str, Any], kind: str,
                  data: Mapping[str, Any]) -> None:
    refund_id = str(data["refund_id"])
    payment_id = str(data.get("payment_id", data.get("attempt_id", "")))
    amount = next((data[key] for key in ("amount_atomic", "atomic_amount", "amount")
                   if data.get(key) is not None), None)
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise ValueError("refund amount must be a non-negative integer in atomic units")
    refund = state["refunds"].setdefault(refund_id, {
        **dict(data), "refund_id": refund_id, "payment_id": payment_id,
        "atomic_amount": amount, "state": "proposed",
    })
    target = {
        "refund_proposed": "proposed", "refund_reserved": "approved_reserved",
        "refund_approved_reserved": "approved_reserved", "refund_submitted": "submitted_unknown",
        "refund_submitted_unknown": "submitted_unknown", "refund_settled": "settled",
        "refund_failed_released": "failed_released",
    }.get(kind)
    if target in {"approved_reserved", "submitted_unknown", "settled"}:
        capture = _canonical_capture(state, payment_id)
        if capture <= 0:
            _exception(state, event, "refund_capture_unknown", refund_id, "no canonical on-chain capture")
            return
        protected = sum(
            item["atomic_amount"] for rid, item in state["refunds"].items()
            if rid != refund_id and item.get("payment_id") == payment_id
            and item.get("state") in {"approved_reserved", "submitted_unknown", "settled"}
        )
        if protected + amount > capture:
            _exception(state, event, "refund_over_capture", refund_id,
                       "completed refunds plus active reservations exceed capture")
            return
    if target:
        refund.update(dict(data))
        refund["atomic_amount"] = amount
        refund["state"] = target
