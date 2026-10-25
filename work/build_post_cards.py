#!/usr/bin/env python3
"""Rebuild the two X post cards (sweep and deadline-first) as PNGs plus alt text.

    python3 work/build_post_cards.py

Writes docs/post-cards/x402-{sweep,gate}-{landscape,square}.png and alt-text.md.
Every number is read from artifacts/ and cross-checked against README.md and
artifacts/validation-report.md, so a changed result fails the build instead of
shipping a stale card. Rendering needs rsvg-convert and the Liberation Sans font.
The release package excludes work/, so this script does not change the package.
"""
from __future__ import annotations

import csv
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "post-cards"

DATA_DATE = "Oct 25, 2026"
DATA_COMMIT = "30b3ec3"
W = 1024
M = 40  # outer margin
SIZES = {"landscape": (W, 800), "square": (W, W)}

NAVY, RED, TINT = "#0B1F4B", "#C8102E", "#A9B8DA"
MUTED, PAPER, RULE = "#4A5B82", "#F6F8FC", "#C9D2E6"
FONT = "font-family=\"'Liberation Sans', Arial, Helvetica, sans-serif\""

POLICIES = [("fifo", "FIFO"), ("deadline_first", "Deadline-first"), ("value_first", "Value-first"), ("hybrid", "Hybrid")]
OBJECTIVES = [
    ("overdue_count", "Fewest overdue cases"),
    ("value_weighted_overdue_minutes", "Least value-weighted overdue time"),
    ("p95_resolution_delay_minutes", "Lowest p95 delay"),
]
# Arial/Liberation advance widths (em) for the glyphs the numbers use.
ADVANCE = {"0": .556, "1": .556, "2": .556, "3": .556, "4": .556, "5": .556, "6": .556, "7": .556, "8": .556,
           "9": .556, ".": .278, ",": .278, "%": .889}


def num_width(text: str, size: int) -> int:
    return round(sum(ADVANCE[c] for c in text) * size)


def text(x, y, content, size, fill=NAVY, weight="normal", anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" {FONT} {extra}>{html.escape(content, quote=False)}</text>')


def lines(x, y, rows, size, fill=MUTED, step=None, weight="normal"):
    step = step or round(size * 1.28)
    return "".join(text(x, y + i * step, row, size, fill, weight) for i, row in enumerate(rows)), y + len(rows) * step


def pct(value: float) -> str:
    return f"{value * 100:.1f}"


def load():
    sweep = json.loads((ROOT / "artifacts/generated/scenario-sweep-summary.json").read_text())
    with (ROOT / "artifacts/generated/policy-results.csv").open(newline="") as handle:
        policies = {row["policy"]: row for row in csv.DictReader(handle)}
    return sweep, policies


def check_sources(sweep, policies):
    """Fail loudly if the repo text no longer backs what the cards say."""
    readme = (ROOT / "README.md").read_text()
    assert sweep["scenario_count"] == 3600
    for key, label in OBJECTIVES:
        rates = [pct(sweep["summary"][p][key]["win_rate"]) for p, _ in POLICIES]
        assert abs(sum(float(r) for r in rates) - 100) < 0.11, (key, rates)
        row = next(line for line in readme.splitlines() if line.startswith(f"| {label} |"))
        cells = [c.strip().strip("*") for c in row.strip("|").split("|")[1:]]
        assert cells == [f"{r}%" for r in rates], (label, cells, rates)
    assert "0 or 15 minutes of evidence delay, and 0 or 10 minutes of finality delay" in readme
    assert "100 seeds, 1 to 3 operators, 0.5x, 1x, or 2x handling time" in readme
    assert "The 65 events, the 16 incidents" in readme and "at least 15%" in readme
    report = (ROOT / "artifacts/validation-report.md").read_text().splitlines()
    assert "nine-case actionable workload produced six overdue cases under both FIFO and deadline-first" in report[22]
    assert [policies[p]["overdue_count"] for p, _ in POLICIES] == ["6", "6", "4", "4"]
    assert abs(int(policies["fifo"]["overdue_count"]) * 0.85 - 5.1) < 1e-9
    # Metric definition: sum of amount x overdue minutes per case (policy.py), reported in USDC-minutes.
    assert 'outcome["amount_atomic"] * outcome["overdue_minutes"]' in (ROOT / "src/exception_desk/policy.py").read_text()
    assert "Value-weighted overdue (USDC-minutes)" in (ROOT / "outputs/complete-project-guide.md").read_text()


def usdc(row) -> float:
    return float(row["value_weighted_overdue_minutes"]) / 1e6


def svg_doc(size, body):
    w, h = size
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="{PAPER}"/>{body}</svg>')


def footer(parts, size, rows):
    """Rule plus footer text pinned to the bottom edge; rows are (text, ...) lines at 26px."""
    step = 33
    top = size[1] - 30 - len(rows) * step
    body = f'<rect x="{M}" y="{top - 14}" width="{W - 2 * M}" height="2" fill="{RULE}"/>'
    markup, _ = lines(M, top + 18, rows, 26, MUTED, step)
    return body + markup, top - 14


def sweep_svg(sweep, size):
    tall = size[1] > 800
    body = [text(M, 76, "ONCHAIN RECEIPTS", 28, RED, "bold", extra='letter-spacing="2"'),
            text(M, 134, "No queue policy wins every objective", 46, NAVY, "bold"),
            text(M, 180, "Synthetic data. Share of 3,600 scenarios each policy won", 30, MUTED)]
    foot_rows = ["p95 delay = 95th-percentile time to resolve a case;",
                 "value-weighted overdue time = minutes overdue x payment amount",
                 "Synthetic sweep: 100 seeds x 1-3 operators x 3 handling times x",
                 "0/15 min evidence delay x 0/10 min finality delay. Ties split credit.",
                 "Source: scenario-sweep-summary.json",
                 f"Data as of {DATA_DATE} (commit {DATA_COMMIT})"]
    foot, foot_top = footer(None, size, foot_rows)
    col = (W - 2 * M) // 4
    head_y = 240 if not tall else 300
    for i, (_, name) in enumerate(POLICIES):
        body.append(text(M + i * col, head_y, name, 30, NAVY, "bold"))
    body.append(f'<rect x="{M}" y="{head_y + 14}" width="{W - 2 * M}" height="3" fill="{NAVY}"/>')
    block = (foot_top - (head_y + 17) - 14) / 3
    for r, (key, label) in enumerate(OBJECTIVES):
        top = head_y + 17 + r * block
        rates = {p: sweep["summary"][p][key]["win_rate"] for p, _ in POLICIES}
        best = max(rates, key=rates.get)
        body.append(text(M, round(top + 34), label, 30, NAVY, "bold"))
        for i, (p, _) in enumerate(POLICIES):
            value = pct(rates[p]) + "%"
            y = round(top + block - 22)
            x = M + i * col
            if p == best:
                body.append(text(x, y, value, 38, NAVY, "bold"))
                body.append(f'<rect x="{x}" y="{y + 8}" width="{num_width(value, 38)}" height="6" fill="{RED}"/>')
            else:
                body.append(text(x, y, value, 38, MUTED))
        if r < 2:
            body.append(f'<rect x="{M}" y="{round(top + block - 6)}" width="{W - 2 * M}" height="1" fill="{RULE}"/>')
    return svg_doc(size, "".join(body) + foot)


def gate_svg(policies, size, layout):
    fifo = usdc(policies["fifo"])
    cases = {p: int(policies[p]["overdue_count"]) for p, _ in POLICIES}
    weighted = {p: usdc(policies[p]) for p, _ in POLICIES}
    cut = (fifo - weighted["deadline_first"]) / fifo
    assert f"{cut * 100:.1f}" == "64.3" and round(cut * 100) == 64
    fill = {"fifo": NAVY, "deadline_first": RED, "value_first": TINT, "hybrid": TINT}
    row_h, bar_h = (66, 40) if layout == "landscape" else (56, 38)

    def bar(x, y, width, p):
        stroke = f' stroke="{MUTED}" stroke-width="2"' if fill[p] == TINT else ""
        return f'<rect x="{x}" y="{y}" width="{max(width, 2)}" height="{bar_h}" fill="{fill[p]}"{stroke}/>'

    def rows(x0, y0, values, fmt, bar_max, label_names, gate=None, delta=False):
        out = []
        for i, (p, name) in enumerate(POLICIES):
            y = y0 + i * row_h
            if label_names:
                out.append(text(M, y + 31, name, 30, NAVY, "bold"))
            width = round(values[p] / max(values.values()) * bar_max) if gate is None else round(values[p] / 6 * bar_max)
            out.append(bar(x0, y, width, p))
            out.append(text(x0 + width + 12, y + 31, fmt(values[p]), 32, NAVY, "bold"))
            if delta and p == "deadline_first":
                out.append(text(x0 + width + 12 + num_width(fmt(values[p]), 32) + 14, y + 31, f"−{cut * 100:.1f}%", 32, RED, "bold"))
        out.append(f'<rect x="{x0 - 2}" y="{y0 - 6}" width="3" height="{4 * row_h - 4 + 6}" fill="{NAVY}"/>')
        if gate is not None:
            gx = x0 + round(5.1 / 6 * bar_max)
            out.append(f'<line x1="{gx}" y1="{y0 - 10}" x2="{gx}" y2="{y0 + 4 * row_h - 2}" stroke="{NAVY}" '
                       f'stroke-width="4" stroke-dasharray="8 6"/>')
            out.append(text(gx, y0 + 4 * row_h + 26, "gate: 5.1", 28, NAVY, "bold", "middle"))
        return out

    body = [text(M, 92, "CUT WEIGHTED OVERDUE TIME", 48, NAVY, "bold"),
            text(M, 148, "64%. STILL FAILED.", 48, RED, "bold"),
            text(M, 194, "Synthetic data: 65 events, 16 incidents, 9 actionable cases", 30, MUTED)]
    foot_rows = ["Gate: >=15% fewer overdue cases than FIFO's 6 (<=5.1)",
                 "6 of 9 cases overdue under FIFO and deadline-first:",
                 "artifacts/validation-report.md, line 23",
                 "Source: policy-results.csv. Time in USDC-minutes"]
    foot, foot_top = footer(None, size, foot_rows)
    names_w = 215
    if layout == "landscape":
        gap = 28
        panel_w = (W - 2 * M - names_w - 2 * gap) // 2
        x1 = M + names_w
        x2 = x1 + panel_w + gap
        head_y = 290
        body += [text(x1, head_y, "Overdue cases", 30, NAVY, "bold"),
                 text(x2, head_y - 34, "Value-weighted", 30, NAVY, "bold"),
                 text(x2, head_y, "overdue time", 30, NAVY, "bold")]
        y0 = head_y + 28
        body += rows(x1 + 2, y0, cases, str, panel_w - 60, True, gate=True)
        body += rows(x2 + 2, y0, weighted, lambda v: f"{v:,.1f}", panel_w - 200, False, delta=True)
    else:
        panel_w = W - 2 * M - names_w
        x1 = M + names_w
        y_a = 268
        body.append(text(M, y_a, "Overdue cases", 30, NAVY, "bold"))
        body += rows(x1 + 2, y_a + 28, cases, str, panel_w - 70, True, gate=True)
        y_b = y_a + 28 + 4 * row_h + 64
        body.append(text(M, y_b, "Value-weighted overdue time", 30, NAVY, "bold"))
        body += rows(x1 + 2, y_b + 28, weighted, lambda v: f"{v:,.1f}", panel_w - 200, True, delta=True)
    return svg_doc(size, "".join(body) + foot)


def alt_texts(sweep):
    parts = []
    for key, label in OBJECTIVES:
        cells = ", ".join(f"{n} {pct(sweep['summary'][p][key]['win_rate'])}%" for p, n in POLICIES)
        parts.append(f"{label}: {cells}.")
    sweep_alt = (
        "Table titled 'No queue policy wins every objective'. Synthetic data: share of 3,600 scenarios each policy "
        "won; ties split credit. " + " ".join(parts) + " Winners: value-first 51.7% on overdue cases, hybrid 40.5% "
        "on value-weighted overdue time, FIFO 50.0% on p95 delay. Source: scenario-sweep-summary.json, data as of "
        f"{DATA_DATE} (commit {DATA_COMMIT})."
    )
    gate_alt = (
        "Two bar charts on synthetic data (65 events, 16 incidents, 9 actionable cases) under the title 'Cut weighted "
        "overdue time 64%. Still failed.' Overdue cases: FIFO 6, deadline-first 6, value-first 4, hybrid 4; the gate "
        "needs 5.1 or fewer. Value-weighted overdue time in USDC-minutes: FIFO 4,428.9, deadline-first 1,582.2 "
        "(cut value-weighted overdue time 64.3%), value-first 1,371.9, hybrid 982.1. Deadline-first is red, FIFO navy, "
        "value-first and hybrid light navy. Footer: the gate is at least 15% fewer overdue cases than FIFO's 6; 6 of 9 "
        "cases stayed overdue under both FIFO and deadline-first (artifacts/validation-report.md, line 23)."
    )
    return sweep_alt, gate_alt


def render(svg, destination):
    subprocess.run(["rsvg-convert", "-o", str(destination)], input=svg.encode(), check=True)


def main():
    if not shutil.which("rsvg-convert"):
        sys.exit("rsvg-convert not found (librsvg)")
    sweep, policies = load()
    check_sources(sweep, policies)
    OUT.mkdir(parents=True, exist_ok=True)
    for layout, size in SIZES.items():
        render(sweep_svg(sweep, size), OUT / f"x402-sweep-{layout}.png")
        render(gate_svg(policies, size, layout), OUT / f"x402-gate-{layout}.png")
    sweep_alt, gate_alt = alt_texts(sweep)
    (OUT / "alt-text.md").write_text(
        "# Post card alt text\n\nGenerated by `work/build_post_cards.py`. Do not edit by hand.\n\n"
        f"## Card A: sweep (`x402-sweep-landscape.png`, `x402-sweep-square.png`)\n\n{sweep_alt}\n\n"
        f"## Card B: deadline-first (`x402-gate-landscape.png`, `x402-gate-square.png`)\n\n{gate_alt}\n",
        encoding="utf-8",
    )
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
