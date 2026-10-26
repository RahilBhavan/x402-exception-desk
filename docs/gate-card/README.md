# Deadline-first gate card for the X post

`x402-gate-square.png` (1080x1080) shows that deadline-first cut value-weighted overdue time 64% (4,428.9 to 1,582.2 USDC-minutes) on 9 synthetic build cases, left 6 vs 6 overdue cases, and so failed the at-least-15% case-count gate. It is not held-out. `alt-text.txt` is the image description (one paragraph).

Every number is read from `artifacts/generated/policy-results.csv`. `build_gate_card.py` stops if a rerun gives different numbers, instead of changing the copy.

Design: Rahil Design charcoal system (`#111214` canvas, `#F5F5EF` ink and figure surface, `#FFE500` accent, Anton display, IBM Plex Sans body). The card is authored at 390x390 CSS px with 22px labels and a 48px title, then exported at 1080x1080. `feed-360.png` and `feed-390.png` show the PNG in a 360px and a 390px feed column (326px and 356px image width). `card.html` holds the fonts inline; `fonts/` has the font files and their licenses. `brief.json` and `measurements.json` hold the measured sizes, contrast and file hashes, and `checks.txt` the check output. `release-rerun.log` is the deterministic build and consistency gate run that the numbers come from.

Rebuild:

```
python3 scripts/release.py
uv run --with playwright==1.63.0 python docs/gate-card/build_gate_card.py
```

The build needs Playwright's Firefox (`~/.cache/ms-playwright/firefox-1555`, or set `FIREFOX`). Two builds give the same PNG bytes. These files are outside the release package, so they do not change the release ZIP checksum.

Review status: design review pending. No passed review record exists for these bytes.
