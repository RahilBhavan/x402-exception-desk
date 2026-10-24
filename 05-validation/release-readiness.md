# Release readiness — 2026-09-22

## Decision

The repository is ready to share as a **independent synthetic case study**. It is not production-ready and does not claim Coinbase endorsement, live x402 interoperability, or practitioner validation. The first policy gate did not justify replacing FIFO; that negative result is retained rather than optimized away.

## Verified evidence

| Check | Command | Result |
|---|---|---|
| Full automated suite | `PYTHONPATH=src python3 -m unittest discover -s tests -v` | PASS — 67 tests (2026-10-24) |
| Reproducible build | `PYTHONPATH=src python3 -m exception_desk.cli --root .` | PASS — stable run `run-a6cf865a0efd58de`; 16 cases; 65 events; 3,600 scenarios |
| Cross-artifact gate | `PYTHONPATH=src python3 -c 'from pathlib import Path; from exception_desk.consistency import assert_artifacts_consistent; print(assert_artifacts_consistent(Path.cwd())["status"])'` | PASS — 26 checks |
| Complete release | `python3 scripts/release.py` | PASS — ZIP and checksum rebuilt in `outputs/x402-exception-desk-package.zip.sha256` |

The gate verifies authoritative input hashes, shared run identity, case/event/oracle counts, four-policy CSV/JSON agreement, scenario count, synthetic labels, and the boundary that chain evidence does not prove delivery.

## Remaining gates

1. Run the existing protocol with up to three qualified payments or operations practitioners. External review is currently unperformed.
2. If the project is ever presented as an integration rather than a simulation, add sandbox interoperability against a pinned x402 implementation and document the accepted finality policy.
3. Validate accessibility and operator comprehension with people, not only markup and deterministic tests.
4. Before any production use, replace synthetic assumptions with representative workload data and complete security, privacy, performance, authorization, and failure-recovery reviews.

PDF, workbook, video, and ZIP integrity are now covered by `scripts/release.py`, `artifacts/package-manifest.json`, and the published ZIP checksum.

These are deliberately described as future gates, not hidden release defects. None is required to understand or reproduce the current local simulation.
