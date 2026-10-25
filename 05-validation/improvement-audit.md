# Improvement audit: artifact integrity and external review

## Automated consistency gate

`exception_desk.consistency.assert_artifacts_consistent(root)` is the release gate. It must run after artifact generation and before packaging. A passing report proves:

- the fixture and oracle bytes match hashes in the build manifest;
- run ID, fixture hash, oracle hash, and policy-workload hash agree across generated JSON, CSV, and HTML outputs;
- projection cases, oracle cases, reconciliation rows, source events, and oracle passes agree with declared counts;
- policy CSV and JSON contain the same policies and metrics;
- every policy was evaluated against the declared workload;
- the declared scenario count agrees between the build summary and sensitivity export;
- machine-readable exports identify the data as synthetic and state that chain evidence does not prove delivery.

Tests include a valid representative bundle plus intentional policy, fixture, count, and labeling drift. Presence-only checks are insufficient.

## Release pass criteria

The gate passes only when every named check returns `PASS`; missing artifacts or metadata fail closed. Run:

```sh
PYTHONPATH=src python3 -m unittest tests.test_consistency -v
PYTHONPATH=src python3 -c 'from pathlib import Path; from exception_desk.consistency import assert_artifacts_consistent; print(assert_artifacts_consistent(Path.cwd())["status"])'
```

Both commands must pass. A passing unit test alone does not certify the current generated package.

## Practitioner-review gate

Use [`../artifacts/operator-task-protocol.md`](../artifacts/operator-task-protocol.md) without changing tasks between participants. External review remains unperformed until at least three qualified practitioners complete all tasks and the exact pass criteria in that protocol are satisfied.

## Remaining gaps

- Fixture and oracle hashes establish byte identity, not real-world representativeness.
- Workload identity establishes a fair policy comparison, not realistic handling-time assumptions.
- Automated checks cannot validate judgment, navigation clarity, or practitioner confidence.
- No external reviewers, live Base transaction, production x402 integration, or customer-data evidence is claimed.
- The cross-artifact gate covers generated JSON, CSV, HTML, and authoritative inputs. The higher-level release command directly hashes the PDF, workbook, and video in `artifacts/package-manifest.json`, then hashes and tests the ZIP. The ZIP has a fixed file order, timestamps and permissions, and its checksum matched on Python 3.9, 3.11 and 3.14 on 2026-10-24; that is not a proof for every platform or zlib build.
