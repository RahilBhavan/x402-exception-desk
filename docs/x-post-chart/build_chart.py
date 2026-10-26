#!/usr/bin/env python3
"""Render the scenario-sweep chart for the X post as a landscape and a square PNG.

Every number comes from artifacts/generated/scenario-sweep-summary.json. The script only formats them:
win rates become one-decimal percentages, and the best policy per objective is the largest raw win rate.
It needs the Python standard library plus Node with Playwright and a browser (`npm install playwright`,
`npx playwright install firefox`). Set PLAYWRIGHT_NODE_MODULES to the node_modules directory if Node cannot find
Playwright, and BROWSER to firefox (default), chromium or webkit.
Outputs, next to this file: scenario-sweep-landscape.png (2048x1280), scenario-sweep-square.png (2048x2048)
and alt-text.txt.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUMMARY = ROOT / "artifacts" / "generated" / "scenario-sweep-summary.json"
SCALE = 2
CANVASES = {"landscape": (1024, 640), "square": (1024, 1024)}

TITLE = "No queue rule wins every objective"
SWEEP_LINE = "0/15 min evidence delay x 0/10 min finality delay"
FOOTNOTE = (
    "p95 delay = 95th-percentile time to resolve a case; "
    "value-weighted overdue time = minutes overdue x payment amount"
)
REPO = "github.com/RahilBhavan/x402-exception-desk"

POLICIES = (
    ("fifo", "FIFO"),
    ("deadline_first", "Deadline-first"),
    ("value_first", "Value-first"),
    ("hybrid", "Hybrid"),
)
OBJECTIVES = (
    ("overdue_count", "Fewest overdue cases"),
    ("value_weighted_overdue_minutes", "Least value-weighted overdue time"),
    ("p95_resolution_delay_minutes", "Lowest p95 delay"),
)

NAVY = "#0b1f4d"
RED = "#d3202f"
ALT_TEXT_LIMIT = 1000  # X rejects longer image descriptions


def percent(win_rate: float) -> str:
    return str((Decimal(repr(win_rate)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) + "%"


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def data_commit() -> tuple[str, str]:
    """Commit date and short SHA of the last commit that changed the summary file."""
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cs %h", "--", str(SUMMARY.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    if len(out) != 2:
        raise RuntimeError("scenario-sweep-summary.json has no commit yet")
    return out[0], out[1]


def build_rows(summary: dict) -> list[dict]:
    rows = []
    for metric, label in OBJECTIVES:
        rates = {key: summary["summary"][key][metric]["win_rate"] for key, _ in POLICIES}
        best = max(rates, key=rates.__getitem__)
        rows.append({
            "label": label,
            "cells": [{"policy": name, "text": percent(rates[key]), "win": key == best} for key, name in POLICIES],
        })
    return rows


def subtitle(summary: dict) -> str:
    return f"Synthetic data: share of {summary['scenario_count']:,} scenarios each rule wins"


def source_line() -> str:
    date, sha = data_commit()
    return f"{REPO} · Data as of {date} ({sha})"


def alt_text(summary: dict, rows: list[dict]) -> str:
    parts = [
        f"Table titled “{TITLE}”. {subtitle(summary)}. Sweep: {SWEEP_LINE}.",
    ]
    for row in rows:
        winner = next(cell for cell in row["cells"] if cell["win"])
        others = ", ".join(f"{c['policy']} {c['text']}" for c in row["cells"] if not c["win"])
        parts.append(f"{row['label']}: {winner['policy']} wins with {winner['text']}; {others}.")
    parts.append("Winning cells are bold navy with a red underline.")
    text = " ".join(parts)
    if len(text) > ALT_TEXT_LIMIT:
        raise ValueError(f"alt text is {len(text)} characters; the limit is {ALT_TEXT_LIMIT}")
    return text


def render_html(kind: str, summary: dict, rows: list[dict]) -> str:
    width, height = CANVASES[kind]
    head = "".join(f"<th>{html.escape(name)}</th>" for _, name in POLICIES)
    body = ""
    for row in rows:
        cells = "".join(
            f"<td class=\"{'win' if c['win'] else ''}\"><span>{c['text']}</span></td>" for c in row["cells"]
        )
        body += f"<tr><th scope=\"row\">{html.escape(row['label'])}</th>{cells}</tr>"
    fonts = HERE / "fonts"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title>
<style>
@font-face {{ font-family: "Roboto Slab"; font-weight: 100 900; src: url("{(fonts / 'RobotoSlab-latin-wght.woff2').as_uri()}"); }}
@font-face {{ font-family: "Archivo"; font-weight: 100 900; src: url("{(fonts / 'Archivo-latin-wght.woff2').as_uri()}"); }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {width}px; height: {height}px; background: #fff; color: {NAVY}; }}
body {{ font-family: "Archivo", sans-serif; font-size: 26px; line-height: 1.25; }}
.card {{ width: {width}px; height: {height}px; display: flex; flex-direction: column; justify-content: space-between; }}
h1 {{ font-family: "Roboto Slab", serif; font-weight: 700; line-height: 1.1; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th, td {{ text-align: left; font-weight: 400; vertical-align: middle; }}
thead th {{ font-weight: 700; border-bottom: 2px solid {NAVY}; }}
tbody tr + tr > * {{ border-top: 1px solid {NAVY}; }}
td {{ font-variant-numeric: tabular-nums; }}
td.win span {{ font-weight: 800; text-decoration: underline; text-decoration-color: {RED};
  text-decoration-thickness: 4px; text-underline-offset: 6px; text-decoration-skip-ink: none; }}
.source {{ font-weight: 500; letter-spacing: -0.015em; white-space: nowrap; }}
.landscape {{ padding: 32px 36px 28px; }}
.landscape h1 {{ font-size: 44px; }}
.landscape .lede {{ margin-top: 6px; }}
.landscape table {{ margin-top: 12px; }}
.landscape col.label {{ width: 41%; }}
.landscape th, .landscape td {{ padding: 11px 0; }}
.landscape td {{ font-size: 30px; }}
.landscape .note {{ margin-top: 12px; }}
.landscape .source {{ margin-top: 6px; }}
.square {{ padding: 64px 56px 56px; }}
.square h1 {{ font-size: 68px; }}
.square .lede {{ margin-top: 20px; }}
.square col.label {{ width: 36%; }}
.square th, .square td {{ padding: 26px 0; }}
.square td {{ font-size: 40px; }}
.square .note {{ margin-top: 0; }}
.square .source {{ margin-top: 14px; }}
</style></head>
<body><main class="card {kind}">
<header><h1>{html.escape(TITLE)}</h1>
<p class="lede">{html.escape(subtitle(summary))}</p>
<p class="sweep">{html.escape(SWEEP_LINE)}</p></header>
<table><colgroup><col class="label"><col><col><col><col></colgroup>
<thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>
<footer><p class="note">{html.escape(FOOTNOTE)}</p>
<p class="source">{html.escape(source_line())}</p></footer>
</main></body></html>
"""


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    return struct.unpack(">II", header[16:24])


def screenshot(page: Path, out: Path, width: int, height: int) -> None:
    """Render with Playwright through render.cjs, which also checks text size, overflow and fill."""
    env = dict(os.environ)
    if os.environ.get("PLAYWRIGHT_NODE_MODULES"):
        env["NODE_PATH"] = os.environ["PLAYWRIGHT_NODE_MODULES"]
    subprocess.run(
        ["node", str(HERE / "render.cjs"), str(page), str(out), str(width), str(height), str(SCALE)],
        check=True, env=env,
    )
    expected = (width * SCALE, height * SCALE)
    if png_size(out) != expected:
        raise RuntimeError(f"{out.name} is {png_size(out)}, expected {expected}")


def main() -> int:
    if not shutil.which("node"):
        sys.exit("node not found; install Node and Playwright (npm install playwright)")
    summary = load_summary()
    rows = build_rows(summary)
    with tempfile.TemporaryDirectory(prefix="chart-html-") as scratch:
        for kind, (width, height) in CANVASES.items():
            page = Path(scratch) / f"{kind}.html"
            page.write_text(render_html(kind, summary, rows), encoding="utf-8")
            screenshot(page, HERE / f"scenario-sweep-{kind}.png", width, height)
    (HERE / "alt-text.txt").write_text(alt_text(summary, rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
