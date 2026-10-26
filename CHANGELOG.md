# Changelog

## Unreleased

### Added

- `docs/x-post-chart/`: the scenario-sweep chart for the X post as a landscape and a square PNG, with its build script and alt text. The numbers come from `scenario-sweep-summary.json`.

### Changed

- The generated SQLite file is no longer tracked or packaged, because its bytes differ between SQLite builds. The release ZIP and checksum now match on Python 3.9, 3.11 and 3.14.
- The release ZIP checksum changed from the one published with v1.1.0. The generated SQLite file left the package, and the earlier ZIP predated the changes in #6.
- Correction to v1.1.0: the entry that says memo PDF rebuilds are byte-identical was not checked. The builder sets fixed dates and a fixed document ID, but the release does not rebuild the memo and CI does not compare rebuilds.
- CI runs `ruff check` and fails if `release.py` changes any tracked file (`git diff --exit-code`).

## v1.1.0 (2026-09-23)

### Fixed

- Refunds are capped at the canonical on-chain capture, not at any observed payment evidence.
- Refund amounts given under the `amount` key are kept instead of read as zero.
- The simulation no longer leaves an operator idle when a case still fits before the horizon.
- Events are ordered by parsed, timezone-aware timestamps instead of raw strings.
- A reused event ID with different content is rejected instead of silently accepted.

### Changed

- Value-weighted overdue time is shown in USDC-minutes in the report, README, memo, and workbook.
- The report, memo, and README state that the project is not affiliated with or endorsed by Coinbase.
- The repository is renamed to `x402-exception-desk`, and the release archive is now `outputs/x402-exception-desk-package.zip`.
- The operator report has link-preview metadata, a favicon, a social card, and a link to the memo PDF, which the site now publishes.
- The memo PDF builds with fixed dates and document ID, so rebuilds are byte-identical.
- A weekly link check and Dependabot updates for GitHub Actions run in CI.
