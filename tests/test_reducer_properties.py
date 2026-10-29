"""Property tests for the guarantees in the ``reduce_events`` docstring.

The project uses only the standard library, so these properties run on a small
seeded generator instead of a property-testing package.  Every example comes
from ``random.Random(f"{property}:{index}")``: the same examples run on every
machine and Python version, and a failure prints the seed and a minimized
event stream that reproduces it.

Properties that the reducer does not satisfy today are kept at full strength
and marked ``expectedFailure``.  Each one names the finding it demonstrates;
when the reducer is fixed the test starts passing, which unittest reports as
an unexpected success, so the marker has to be removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import unittest
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import exception_desk
from exception_desk.reducer import project_case, reduce_events
from exception_desk.store import InvalidEvent

SRC = Path(exception_desk.__file__).resolve().parents[1]
EXAMPLES = 200

ORIGIN = datetime(2027, 1, 1, tzinfo=timezone.utc)
ATTEMPT_ORDER = {"attempt-1": "order-1", "attempt-2": "order-2", "attempt-3": "order-1"}
ORDERS = tuple(sorted(set(ATTEMPT_ORDER.values())))
# (network, transaction_ref, log_index, atomic amount): an on-chain payment always carries one amount.
CLAIMS = (("base", "0xa", 0, 100), ("base", "0xa", 1, 60), ("base", "0xb", 0, 40))
# refund_id: (payment attempt, atomic amount)
REFUNDS = {"r1": ("attempt-1", 70), "r2": ("attempt-1", 40), "r3": ("attempt-2", 100), "r4": ("attempt-3", 30)}
REFUND_KINDS = ("refund_proposed", "refund_reserved", "refund_approved_reserved", "refund_submitted",
                "refund_submitted_unknown", "refund_settled", "refund_failed_released")
PROTECTED = {"approved_reserved", "submitted_unknown", "settled"}
GUARD_EXCEPTIONS = {"refund_over_capture", "refund_capture_unknown", "evidence_claim_conflict",
                    "missing_payment_attempt"}

Event = dict
Stream = list


def _stamp(rng: random.Random, instant: datetime) -> str:
    zone = rng.choice((None, 0, 2, -5))
    if zone is None:
        return instant.isoformat().replace("+00:00", "Z")
    return instant.astimezone(timezone(timedelta(hours=zone))).isoformat()


def _envelope(rng: random.Random, index: int, kind: str, data: dict, fixture_order: Optional[str]) -> Event:
    """Events arrive roughly in generation order, so orders, payments and refunds tend to line up."""
    observed = ORIGIN + timedelta(minutes=max(0, index * 3 + rng.randint(-4, 4)))
    event = {"event_id": f"ev-{index}", "observed_at": _stamp(rng, observed)}
    if rng.random() < 0.4:
        event["occurred_at"] = _stamp(rng, observed - timedelta(minutes=rng.randint(0, 3)))
    if rng.random() < 0.3:
        event["sequence"] = rng.randint(0, 5)
    if fixture_order is None:
        event.update(type=kind, data=data)
    else:
        event.update(event_type=kind, aggregate_id=fixture_order, payload=data)
    return event


def random_stream(rng: random.Random, reobserve: bool = True, invalidate: bool = True) -> Stream:
    """A valid stream: every event satisfies the envelope and field contracts.

    ``reobserve=False`` reports each on-chain payment at most once and
    ``invalidate=False`` leaves out reorg invalidations.
    """
    events: Stream = []
    seen_claims: set = set()

    def observation() -> dict:
        claims = [c for c in CLAIMS if reobserve or c[:3] not in seen_claims]
        if not claims:
            return {}
        network, tx, log, amount = rng.choice(claims)
        seen_claims.add((network, tx, log))
        return {"network": network, "transaction_ref": tx, "log_index": log, "amount_atomic": amount}

    def make(index: int) -> Event:
        order = rng.choice(ORDERS)
        attempt = rng.choice([a for a, o in ATTEMPT_ORDER.items() if o == order])
        refund_id = rng.choice(sorted(REFUNDS))
        refund_payment, refund_amount = REFUNDS[refund_id]
        amount_key = rng.choice(("atomic_amount", "amount_atomic", "amount"))
        fixture = rng.random() < 0.3
        choice = rng.choice((
            "order", "order", "attempt", "attempt", "observe", "observe", "observe", "timeout", "fail",
            "invalidate", "prepare", "deliver", "deliver_fail", "refund", "refund", "refund", "refund",
            "note", "control",
        ))
        if choice == "invalidate" and not invalidate:
            choice = "note"
        if choice == "order":
            amount = rng.choice((10, 100, 250))
            if fixture:
                return _envelope(rng, index, "order_opened", {"expected_amount_atomic": amount}, order)
            return _envelope(rng, index, "order_created", {"order_id": order, "expected_atomic_amount": amount}, None)
        if choice == "attempt":
            if fixture:
                return _envelope(rng, index, "authorization_verified", {"attempt_id": attempt}, order)
            return _envelope(rng, index, "payment_attempt_submitted", {"attempt_id": attempt, "order_id": order}, None)
        if choice == "observe":
            seen = observation()
            if not seen:
                return _envelope(rng, index, "duplicate_request_received", {"request_id": f"req-{index}"}, order)
            if fixture:
                return _envelope(rng, index, "payment_observed",
                                 {"attempt_id": attempt, **seen, "finality_stage": "l2_inclusion"}, order)
            return _envelope(rng, index, "chain_observed", {"attempt_id": attempt, **seen}, None)
        if choice in {"timeout", "fail"}:
            names = {"timeout": ("settlement_timed_out", "payment_attempt_timed_out"),
                     "fail": ("settlement_failed", "payment_attempt_failed")}[choice]
            return (_envelope(rng, index, names[0], {"attempt_id": attempt}, order) if fixture
                    else _envelope(rng, index, names[1], {"attempt_id": attempt}, None))
        if choice == "invalidate":
            network, tx, log, _ = rng.choice(CLAIMS)
            payload = {"transaction_ref": tx, "log_index": log}
            return (_envelope(rng, index, "chain_observation_invalidated", payload, order) if fixture
                    else _envelope(rng, index, "chain_observation_invalidated", {"order_id": order, **payload}, None))
        if choice in {"prepare", "deliver", "deliver_fail"}:
            names = {"prepare": ("resource_prepared", "fulfillment_prepared"),
                     "deliver": ("delivery_acknowledged", "fulfillment_delivered"),
                     "deliver_fail": ("delivery_failed", "fulfillment_delivery_failed")}[choice]
            return (_envelope(rng, index, names[0], {"delivery_id": f"delivery-{index}"}, order) if fixture
                    else _envelope(rng, index, names[1], {"order_id": order}, None))
        if choice == "refund":
            kind = rng.choice(REFUND_KINDS)
            payload = {"refund_id": refund_id, "payment_id": refund_payment, amount_key: refund_amount}
            return (_envelope(rng, index, kind, payload, ATTEMPT_ORDER[refund_payment]) if fixture
                    else _envelope(rng, index, kind, payload, None))
        if choice == "control":
            kind = rng.choice(("authorization_rejected", "ingestion_replay_detected", "payment_evidence_received"))
            return _envelope(rng, index, kind, {"attempt_id": attempt}, order)
        return _envelope(rng, index, "exception_opened", {"exception_id": f"exc-{rng.randint(0, 3)}"}, None)

    for index in range(rng.randint(4, 26)):
        events.append(make(index))
    return events


def duplicates_and_shuffle(events: Stream, rng: random.Random) -> Stream:
    extra = [deepcopy(e) for e in events if rng.random() < 0.5]
    mixed = [deepcopy(e) for e in events] + extra
    rng.shuffle(mixed)
    return mixed


def fails(prop: Callable[[Stream, random.Random], None], events: Stream, seed: str) -> Optional[BaseException]:
    try:
        prop(deepcopy(events), random.Random(seed))
    except Exception as exc:  # a crash on a valid stream is also a counterexample
        return exc
    return None


def minimize(events: Stream, still_fails: Callable[[Stream], bool]) -> Stream:
    """Greedily drop events while the property keeps failing."""
    current = list(events)
    shrunk = True
    while shrunk:
        shrunk = False
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1:]
            if candidate and still_fails(candidate):
                current, shrunk = candidate, True
                break
    return current


def snapshot_hash(state: Any, ordered: bool) -> str:
    encoded = json.dumps(state, sort_keys=not ordered, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def distinct_capture(state: dict, payment_id: str) -> int:
    """On-chain amount for one payment: each canonical on-chain claim counts once."""
    claims = {}
    for observation in state["chain_observations"].values():
        if observation.get("canonical", True) and str(observation.get("attempt_id")) == payment_id:
            claims[observation["claim_key"]] = observation["amount_atomic"]
    return sum(claims.values())


def protected_by_payment(state: dict) -> dict:
    totals: Counter = Counter()
    for refund in state["refunds"].values():
        if refund["state"] in PROTECTED:
            totals[refund["payment_id"]] += refund["atomic_amount"]
    return totals


def balance_view(state: dict) -> dict:
    """Protected balance and entitlement state: refunds, orders, captured evidence and fulfillments."""
    return {
        "refunds": {rid: (r["payment_id"], r["atomic_amount"], r["state"])
                    for rid, r in state["refunds"].items() if r["state"] in PROTECTED},
        "orders": {oid: (o["payment_state"], o["delivery_state"]) for oid, o in state["orders"].items()},
        "observations": {oid: (o.get("canonical", True), o["amount_atomic"])
                         for oid, o in state["chain_observations"].items() if "amount_atomic" in o},
        "claims": dict(state["evidence_claims"]),
        "fulfillments": {oid: f["state"] for oid, f in state["fulfillments"].items()},
    }


class PropertyCase(unittest.TestCase):
    def check(self, name: str, prop: Callable[[Stream, random.Random], None], **profile: Any) -> None:
        for index in range(EXAMPLES):
            seed = f"{name}:{index}"
            events = random_stream(random.Random(seed), **profile)
            error = fails(prop, events, seed)
            if error is None:
                continue
            small = minimize(events, lambda candidate, seed=seed: fails(prop, candidate, seed) is not None)
            self.fail(f"{name} failed for seed {seed!r} with {error!r}\n"
                      f"minimal stream ({len(small)} of {len(events)} events):\n"
                      f"{json.dumps(small, indent=1, sort_keys=True)}")


class ReplayTests(PropertyCase):
    def test_shuffling_and_duplicating_any_subset_reduces_to_identical_state(self):
        def prop(events, rng):
            original = deepcopy(events)
            expected = reduce_events(events)
            self.assertEqual(original, events, "reduce_events mutated its input")
            actual = reduce_events(duplicates_and_shuffle(events, rng))
            self.assertEqual(expected, actual)
            self.assertEqual(snapshot_hash(expected, ordered=True), snapshot_hash(actual, ordered=True))
            self.assertEqual(project_case(events), project_case(duplicates_and_shuffle(events, rng)))
            self.assertEqual(expected, reduce_events(events + events))

        self.check("replay", prop)

    def test_reusing_an_event_id_with_different_content_raises_invalid_event(self):
        mutations = []

        def annotate(event):
            holder = event["data"] if "data" in event else event["payload"]
            holder["note"] = "changed"

        def move_occurred_at(event):
            event["occurred_at"] = "2020-01-01T00:00:00Z"

        def bump_amount(event):
            holder = event["data"] if "data" in event else event["payload"]
            keys = [k for k in ("amount_atomic", "atomic_amount", "amount", "expected_atomic_amount",
                                "expected_amount_atomic") if k in holder]
            if not keys:
                raise LookupError
            holder[keys[0]] += 1

        mutations.extend([annotate, move_occurred_at, bump_amount])
        applied: Counter = Counter()

        def prop(events, rng):
            victim = rng.choice(events)
            mutate = rng.choice(mutations)
            changed = deepcopy(victim)
            try:
                mutate(changed)
            except LookupError:
                mutate = annotate
                mutate(changed)
            others = [e for e in events if e["event_id"] != victim["event_id"]]
            reduce_events(others + [changed])  # the variant is a valid event by itself
            applied[mutate.__name__] += 1
            stream = events + [changed]
            rng.shuffle(stream)
            with self.assertRaises(InvalidEvent):
                reduce_events(stream)

        self.check("conflict", prop)
        self.assertEqual(3, len(applied), f"every mutation kind must run: {dict(applied)}")


class AmountTests(PropertyCase):
    def test_generated_streams_keep_every_amount_an_integer_and_non_negative(self):
        def is_amount(value):
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0

        def prop(events, rng):
            state = reduce_events(events)
            for order in state["orders"].values():
                self.assertTrue(is_amount(order["expected_atomic_amount"]), order)
            for refund in state["refunds"].values():
                self.assertTrue(is_amount(refund["atomic_amount"]), refund)
            for observation in state["chain_observations"].values():
                if "amount_atomic" in observation:
                    self.assertTrue(is_amount(observation["amount_atomic"]), observation)
            for name, value in project_case(events)["expected_financials"].items():
                self.assertTrue(is_amount(value), (name, value))

        self.check("amounts", prop)

    def test_order_and_refund_amounts_that_are_not_non_negative_integers_are_rejected(self):
        bad_amounts = (1.5, 100.0, "100", True, False, None, -1, [100])
        observed = [
            {"event_id": "o", "type": "order_created", "observed_at": "2027-01-01T00:00:00Z",
             "data": {"order_id": "order-1", "expected_atomic_amount": 100}},
            {"event_id": "a", "type": "payment_attempt_submitted", "observed_at": "2027-01-01T00:01:00Z",
             "data": {"attempt_id": "attempt-1", "order_id": "order-1"}},
            {"event_id": "c", "type": "chain_observed", "observed_at": "2027-01-01T00:02:00Z",
             "data": {"attempt_id": "attempt-1", "network": "base", "transaction_ref": "0x1", "log_index": 0,
                      "amount_atomic": 100}},
        ]
        for amount in bad_amounts:
            order = {"event_id": "o2", "type": "order_created", "observed_at": "2027-01-01T00:00:00Z",
                     "data": {"order_id": "order-2", "expected_atomic_amount": amount}}
            with self.subTest(order_amount=amount):
                with self.assertRaises(ValueError):
                    reduce_events([order])
            for kind in REFUND_KINDS:
                for key in ("atomic_amount", "amount_atomic", "amount"):
                    refund = {"event_id": "r", "type": kind, "observed_at": "2027-01-01T00:03:00Z",
                              "data": {"refund_id": "r1", "payment_id": "attempt-1", key: amount}}
                    with self.subTest(refund_kind=kind, key=key, amount=amount):
                        with self.assertRaises(ValueError):
                            reduce_events(observed + [refund])

    @unittest.expectedFailure
    def test_finding_chain_observation_amounts_are_not_validated(self):
        """Finding: ``amount_atomic`` on a chain observation is coerced with ``int()``, never checked.

        A float is stored as-is and truncated in the capture total, ``True`` counts as 1,
        and a negative amount lowers the capture, unlike order and refund amounts.
        """
        def prop(events, rng):
            amount = rng.choice((100.7, "100", True, -5))
            stream = [e for e in events if e["event_id"] != "bad"] + [{
                "event_id": "bad", "type": "chain_observed", "observed_at": "2027-01-01T00:30:00Z",
                "data": {"attempt_id": "attempt-9", "network": "base", "transaction_ref": "0xbad",
                         "log_index": 0, "amount_atomic": amount}}, {
                "event_id": "bad-attempt", "type": "payment_attempt_submitted",
                "observed_at": "2027-01-01T00:29:00Z", "data": {"attempt_id": "attempt-9", "order_id": "order-9"}}]
            try:
                state = reduce_events(stream)
            except ValueError:
                return
            stored = state["chain_observations"]["bad"]["amount_atomic"]
            self.assertTrue(isinstance(stored, int) and not isinstance(stored, bool) and stored >= 0,
                            f"stored {stored!r}")

        self.check("observation-amounts", prop)


class RejectedTransitionTests(PropertyCase):
    def test_events_the_reducer_rejects_leave_balances_and_entitlements_untouched(self):
        hits: Counter = Counter()

        def prop(events, rng):
            state = reduce_events(events)
            rejected = [x for x in state["exceptions"].values() if x.get("type") in GUARD_EXCEPTIONS]
            for exception in rejected:
                hits[exception["type"]] += 1
                without = [e for e in events if e["event_id"] != exception["source_event_id"]]
                self.assertEqual(balance_view(reduce_events(without)), balance_view(state),
                                 f"{exception['type']} from {exception['source_event_id']} changed state")
                self.assertEqual(project_case(without)["expected_financials"],
                                 project_case(events)["expected_financials"])

        self.check("rejected", prop)
        self.assertEqual(GUARD_EXCEPTIONS, set(hits), f"every guard must be exercised: {dict(hits)}")

    @unittest.expectedFailure
    def test_finding_a_settled_refund_can_be_moved_back_by_a_later_event(self):
        """Finding: ``_apply_refund`` accepts any refund event for an existing refund.

        A settled refund moves back to proposed, reserved or failed_released with no exception, so the
        completed-refund balance silently drops.
        """
        def prop(events, rng):
            seen_settled: set = set()
            prefix: Stream = []
            for event in sorted_for_replay(events):
                prefix.append(event)
                refunds = reduce_events(prefix)["refunds"]
                self.assertTrue(seen_settled <= {rid for rid, r in refunds.items() if r["state"] == "settled"},
                                f"settled refund left the settled state after {event['event_id']}")
                seen_settled |= {rid for rid, r in refunds.items() if r["state"] == "settled"}

        self.check("settled-terminal", prop)


def sorted_for_replay(events: Stream) -> Stream:
    """Distinct events in the reducer's replay order, read from its own projection."""
    by_id = {e["event_id"]: e for e in events}
    return [by_id[event_id] for event_id in reduce_events(events)["applied_event_ids"]]


class CaptureTests(PropertyCase):
    def refunds_within_capture(self, events, rng):
        state = reduce_events(events)
        for payment_id, total in protected_by_payment(state).items():
            capture = distinct_capture(state, payment_id)
            self.assertLessEqual(total, capture, f"refunds of {payment_id} exceed on-chain capture")

    def test_refunds_never_exceed_capture_when_each_payment_is_observed_once_and_never_invalidated(self):
        self.check("refund-cap", self.refunds_within_capture, reobserve=False, invalidate=False)

    @unittest.expectedFailure
    def test_finding_one_payment_observed_twice_is_captured_twice(self):
        """Finding: a second observation of the same claim is added to the capture again.

        Two ``chain_observed`` events for one transaction and log index (new event_id each) pass the claim
        check because the order is the same, and ``_canonical_capture`` sums both, so refunds up to twice
        the payment are admitted.
        """
        self.check("refund-cap-reobserved", self.refunds_within_capture, invalidate=False)

    @unittest.expectedFailure
    def test_finding_a_reorg_after_a_refund_leaves_the_refund_above_capture(self):
        """Finding: the capture check runs only when a refund event is applied.

        Invalidating the observation afterwards drops the capture to zero while the settled refund stays
        settled and no exception is opened.
        """
        self.check("refund-cap-invalidated", self.refunds_within_capture, reobserve=False)


class EvidenceTests(PropertyCase):
    def test_one_payment_never_satisfies_two_orders(self):
        def prop(events, rng):
            state = reduce_events(events)
            owners: dict = {}
            for observation in state["chain_observations"].values():
                if not observation.get("canonical", True):
                    continue
                attempt = state["payment_attempts"][str(observation["attempt_id"])]
                owners.setdefault(observation["claim_key"], set()).add(attempt["order_id"])
            for claim_key, orders in owners.items():
                self.assertEqual(1, len(orders), f"{claim_key} backs orders {sorted(orders)}")
            satisfied: dict = {}
            for attempt in state["payment_attempts"].values():
                if attempt["outcome"] == "observed":
                    satisfied.setdefault(attempt["evidence_claim"], set()).add(attempt["order_id"])
            for claim_key, orders in satisfied.items():
                self.assertEqual(1, len(orders), f"{claim_key} marks orders {sorted(orders)} as paid")
            for order_id, order in state["orders"].items():
                if order["payment_state"] == "observed":
                    claims = {a["evidence_claim"] for a in state["payment_attempts"].values()
                              if a["order_id"] == order_id and a["outcome"] == "observed"}
                    self.assertTrue(claims, f"{order_id} is observed without an observed attempt")

        self.check("one-payment", prop)

    def test_the_second_order_to_claim_a_payment_is_refused_with_an_exception(self):
        claimed: Counter = Counter()

        def prop(events, rng):
            state = reduce_events(events)
            for exception in state["exceptions"].values():
                if exception.get("type") == "evidence_claim_conflict":
                    claimed["conflicts"] += 1
                    event_id = exception["source_event_id"]
                    self.assertNotIn(event_id, state["chain_observations"])

        self.check("claim-conflict", prop)
        self.assertGreater(claimed["conflicts"], 0)


class SnapshotTests(unittest.TestCase):
    def test_the_same_stream_has_the_same_snapshot_hash_in_every_run(self):
        streams = [random_stream(random.Random(f"snapshot:{i}")) for i in range(40)]
        expected = [snapshot_hash(reduce_events(s), ordered=True) for s in streams]
        self.assertEqual(expected, [snapshot_hash(reduce_events(s), ordered=True) for s in streams])
        self.assertEqual([snapshot_hash(reduce_events(s), ordered=False) for s in streams],
                         [snapshot_hash(reduce_events(s), ordered=False) for s in streams])
        code = (
            "import hashlib, json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from exception_desk.reducer import reduce_events\n"
            "streams = json.load(sys.stdin)\n"
            "print(json.dumps([hashlib.sha256(json.dumps(reduce_events(s), separators=(',', ':'))"
            ".encode()).hexdigest() for s in streams]))\n"
        )
        for hash_seed in ("0", "1", "4242", "random"):
            with self.subTest(PYTHONHASHSEED=hash_seed):
                completed = subprocess.run(
                    [sys.executable, "-c", code, str(SRC)], input=json.dumps(streams), text=True,
                    capture_output=True, check=True, env=dict(os.environ, PYTHONHASHSEED=hash_seed),
                )
                self.assertEqual(expected, json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
