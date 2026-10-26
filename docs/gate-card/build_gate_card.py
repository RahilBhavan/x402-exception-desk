#!/usr/bin/env python3
"""Render the deadline-first gate card for the X post in the Rahil Design charcoal system.

    uv run --with playwright==1.63.0 python docs/gate-card/build_gate_card.py

Every number is read from artifacts/generated/policy-results.csv and checked against the copy the post uses
(4,428.9 -> 1,582.2 USDC-minutes, -64%, 6 vs 6 overdue cases). If a rerun changes a number, the build stops
instead of changing the copy. The card is authored at 390x390 CSS px and exported at 1080x1080; the 360px and
390px feed screenshots show that PNG inside a feed column. Outputs, next to this file: card.html (fonts embedded),
x402-gate-square.png, feed-360.png, feed-390.png, alt-text.txt and measurements.json.
Colours are the Rahil Design tokens (assets/tokens.json) and fonts are the bundled Anton and IBM Plex Sans.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import json
import os
import struct
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
POLICY_CSV = ROOT / "artifacts" / "generated" / "policy-results.csv"
FONTS = HERE / "fonts"

CANVAS, EXPORT = 390, 1080  # authored CSS px, exported px
LABEL_PX, TITLE_PX, VALUE_PX = 22, 48, 28
FEED_FLOOR_LABEL, FEED_FLOOR_POINT = 18, 40  # tokens feed.label-floor and feed.point-floor
FEED_BOX = {360: 326, 390: 356}  # image width inside a 360px and a 390px feed column

# tokens.json (rahil-design): color and font roles used by this card
C = {"canvas": "#111214", "ink": "#F5F5EF", "secondary": "#B7B8B1", "accent": "#FFE500",
     "figure-surface": "#F5F5EF", "figure-ink": "#111214", "figure-secondary": "#52545A"}

DATA_DATE = "Oct 26, 2026"
TITLE = "Cut overdue time 64%. Gate failed."
CONTEXT = "FIFO \u2192 Deadline-first"
GATE = "Gate: \u226515% fewer. Failed."
SOURCE_LINES = ("9 synthetic build cases,", f"not held-out. {DATA_DATE}.", "Source: policy-results.csv")
EXPECTED = {"fifo": ("6", "4,428.9"), "deadline_first": ("6", "1,582.2")}  # copy the post makes; a rerun must match


def usdc_minutes(row: dict) -> Decimal:
    return (Decimal(row["value_weighted_overdue_minutes"]) / Decimal(10) ** 6).quantize(Decimal("0.1"), ROUND_HALF_UP)


def load_numbers() -> dict:
    with POLICY_CSV.open(newline="") as handle:
        rows = {r["policy"]: r for r in csv.DictReader(handle)}
    got = {p: (rows[p]["overdue_count"], f"{usdc_minutes(rows[p]):,.1f}") for p in EXPECTED}
    if got != EXPECTED:
        sys.exit(f"policy-results.csv differs from the post copy: {got} vs {EXPECTED}. Report it; do not edit the copy silently.")
    fifo, deadline = (Decimal(rows[p]["value_weighted_overdue_minutes"]) for p in EXPECTED)
    cut = (fifo - deadline) / fifo
    if (cut * 100).quantize(Decimal("1"), ROUND_HALF_UP) != 64:
        sys.exit(f"cut is {cut:.4f}, not 64%")
    fewer = 1 - Decimal(rows["deadline_first"]["overdue_count"]) / Decimal(rows["fifo"]["overdue_count"])
    if fewer >= Decimal("0.15"):
        sys.exit("the 15% case-count gate would pass; the card says it failed")
    return {"overdue": got, "cut_pct": 64, "fewer_cases_pct": float(fewer)}


def card_html() -> str:
    def font(name: str) -> str:
        return base64.b64encode((FONTS / name).read_bytes()).decode()

    (o_fifo, w_fifo), (o_dead, w_dead) = EXPECTED["fifo"], EXPECTED["deadline_first"]
    arrow = "\u2192"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title><style>
@font-face{{font-family:'Rahil Display';src:url(data:font/ttf;base64,{font('Anton-Regular.ttf')})}}
@font-face{{font-family:'Rahil Plex';src:url(data:font/ttf;base64,{font('IBMPlexSans-Regular.ttf')})}}
*{{box-sizing:border-box}}html,body{{margin:0}}
body{{width:{CANVAS}px;height:{CANVAS}px;background:{C['canvas']};color:{C['ink']};font-family:'Rahil Plex',sans-serif}}
article{{width:{CANVAS}px;height:{CANVAS}px;padding:20px;display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr) auto;gap:8px}}
h1{{font:{TITLE_PX}px/1.02 'Rahil Display',sans-serif;margin:0;text-transform:uppercase}}
.figure{{background:{C['figure-surface']};color:{C['figure-ink']};padding:4px 14px;display:flex;flex-direction:column;justify-content:center;gap:0;font-size:{LABEL_PX}px;line-height:1.05}}
.row{{display:flex;justify-content:space-between;align-items:center}}
.name{{color:{C['figure-secondary']}}}
.num{{font:{VALUE_PX}px/1 'Rahil Display',sans-serif;font-variant-numeric:tabular-nums;white-space:nowrap}}
.focus{{display:inline-block;background:{C['accent']};color:{C['figure-ink']};outline:2px solid {C['figure-ink']};padding:0 6px;margin-left:8px;font-size:{LABEL_PX}px;line-height:1.1;font-family:'Rahil Plex',sans-serif}}
.gate{{padding-bottom:2px}}
.source{{font-size:{LABEL_PX}px;line-height:1.1;white-space:nowrap;color:{C['secondary']};margin:0}}
</style></head><body><article><h1>{html.escape(TITLE)}</h1>
<section class="figure" aria-label="FIFO {arrow} Deadline-first on 9 synthetic build cases">
<div class="name">{CONTEXT}</div>
<div class="row"><span class="name">Overdue cases</span><span class="num">{o_fifo} {arrow} {o_dead}</span></div>
<div class="name gate">{html.escape(GATE)}</div>
<div class="name">Value-weighted overdue time, USDC-minutes</div>
<div class="row"><span class="num">{w_fifo} {arrow} {w_dead}</span><span class="focus">\u221264%</span></div></section>
<p class="source">{"<br>".join(html.escape(line) for line in SOURCE_LINES)}</p></article></body></html>
"""


MEASURE = """() => {
  const out = {sizes: [], overflow: [], fonts: [], title_lines: 0};
  const art = document.querySelector('article'), box = art.getBoundingClientRect(), pad = getComputedStyle(art);
  const px = k => parseFloat(pad[k]);
  const fig = document.querySelector('.figure'), fr = fig.getBoundingClientRect();
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    out.sizes.push([el.className || el.tagName, parseFloat(cs.fontSize)]);
    out.fonts.push(cs.fontFamily.split(',')[0].replace(/["']/g, '').trim());
    if (el.scrollWidth > el.clientWidth + 1 || r.right > box.right - px('paddingRight') + 0.5 || r.bottom > box.bottom - px('paddingBottom') + 0.5 || r.left < box.left + px('paddingLeft') - 0.5)
      out.overflow.push('outside the padded card: ' + el.textContent.slice(0, 40));
  }
  for (const el of fig.querySelectorAll('*')) { const r = el.getBoundingClientRect();
    if (r.height && (r.top < fr.top - 0.5 || r.bottom > fr.bottom + 0.5 || r.right > fr.right - 13 || r.left < fr.left + 13))
      out.overflow.push('outside the figure padding: ' + el.textContent.slice(0, 40)); }
  if (fig.scrollHeight > fig.clientHeight + 1) out.overflow.push('figure content taller than its box');
  const h1 = document.querySelector('h1');
  out.title_lines = Math.round(h1.getBoundingClientRect().height / parseFloat(getComputedStyle(h1).lineHeight));
  out.loaded = ['Rahil Display', 'Rahil Plex'].map(f => [f, [...document.fonts].some(x => x.family.replace(/["']/g, '') === f && x.status === 'loaded')]);
  const bottom = Math.max(...[...document.querySelectorAll('.source')].map(e => e.getBoundingClientRect().bottom));
  out.slack_bottom = box.bottom - px('paddingBottom') - bottom;
  return out;
}"""


def contrast(a: str, b: str) -> float:
    def lum(hex_color: str) -> float:
        channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = (("ink", "canvas"), ("secondary", "canvas"), ("figure-ink", "figure-surface"),
         ("figure-secondary", "figure-surface"), ("figure-ink", "accent"))


def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


def launch(playwright):
    exe = os.environ.get("FIREFOX") or str(Path.home() / ".cache/ms-playwright/firefox-1555/firefox/firefox")
    return playwright.firefox.launch(headless=True, executable_path=exe if Path(exe).exists() else None)


def render(card: Path, png: Path) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": CANVAS, "height": CANVAS}, device_scale_factor=EXPORT / CANVAS)
        page.goto(card.as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        measured = page.evaluate(MEASURE)
        page.screenshot(path=str(png))
        browser.close()
    return measured


def feed_shots(png: Path) -> dict:
    """Show the exported PNG in a 360px and a 390px feed column and measure the displayed text sizes."""
    from playwright.sync_api import sync_playwright
    shown = {}
    data = base64.b64encode(png.read_bytes()).decode()
    with sync_playwright() as p:
        browser = launch(p)
        for width, box in FEED_BOX.items():
            page = browser.new_page(viewport={"width": width, "height": box + 48}, device_scale_factor=2)
            page.set_content(
                f"<body style='margin:0;background:{C['canvas']}'><img alt='' src='data:image/png;base64,{data}' "
                f"style='display:block;margin:24px {(width - box) // 2}px;width:{box}px;height:{box}px'></body>")
            page.wait_for_function("document.images[0].complete && document.images[0].naturalWidth > 0")
            page.screenshot(path=str(HERE / f"feed-{width}.png"))
            page.close()
            scale = box / CANVAS
            shown[width] = {"image_px": box, "scale": round(scale, 4), "label_px": round(LABEL_PX * scale, 2),
                            "title_px": round(TITLE_PX * scale, 2)}
        browser.close()
    return shown


def alt_text(numbers: dict) -> str:
    (o_f, w_f), (o_d, w_d) = EXPECTED["fifo"], EXPECTED["deadline_first"]
    return (f"Card titled ‘{TITLE}’ on 9 synthetic build cases, FIFO against deadline-first. "
            f"Overdue cases: {o_f} against {o_d}. Value-weighted overdue time in USDC-minutes: {w_f} against {w_d}, "
            f"a cut of {numbers['cut_pct']}%, highlighted in yellow. The gate needed at least 15% fewer overdue cases "
            f"and failed. Not held-out. Source: policy-results.csv, as of {DATA_DATE}.")


def main() -> int:
    numbers = load_numbers()
    card, png = HERE / "card.html", HERE / "x402-gate-square.png"
    card.write_text(card_html(), encoding="utf-8")
    measured = render(card, png)
    sizes = [px for _, px in measured["sizes"]]
    errors = [f"overflow: {o}" for o in measured["overflow"]]
    errors += [f"font {f!r} is not a token font" for f in set(measured["fonts"]) - {"Rahil Display", "Rahil Plex"}]
    errors += [f"font {f} not loaded" for f, ok in measured["loaded"] if not ok]
    errors += [f"text below {LABEL_PX}px"] * (min(sizes) < LABEL_PX)
    if png_size(png) != (EXPORT, EXPORT):
        errors.append(f"{png.name} is {png_size(png)}, expected {EXPORT}x{EXPORT}")
    shown = feed_shots(png)
    for width, s in shown.items():
        if s["label_px"] < FEED_FLOOR_LABEL or s["title_px"] < FEED_FLOOR_POINT:
            errors.append(f"{width}px feed: label {s['label_px']}px or title {s['title_px']}px is below the floor")
    alt = alt_text(numbers)
    if "\n" in alt or len(alt) > 1000:
        errors.append(f"alt text must be one paragraph under 1000 characters ({len(alt)})")
    (HERE / "alt-text.txt").write_text(alt + "\n", encoding="utf-8")
    contrast_min = min(contrast(C[a], C[b]) for a, b in PAIRS)
    report = {"numbers": numbers, "min_label_px": min(sizes), "title_px": TITLE_PX, "title_lines": measured["title_lines"],
              "slack_bottom_px": round(measured["slack_bottom"], 1), "feed": shown,
              "sha256": {n: hashlib.sha256((HERE / n).read_bytes()).hexdigest()
                         for n in ("card.html", png.name, "feed-360.png", "feed-390.png")}}
    report["contrast_min"] = round(contrast_min, 2)
    (HERE / "measurements.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    brief = {
        "id": "x402-gate-card-square", "set": "x-week-2026-10-26", "template": "rahil-design-card", "accent_meaning": "title-value",
        "reader": "Payments or product engineer on X, phone width",
        "decision": "Keep FIFO: deadline-first cut weighted overdue time but missed the case-count gate",
        "point": "Deadline-first cut value-weighted overdue time 64% on 9 synthetic build cases but left 6 vs 6 overdue cases, so the at-least-15% case-count gate failed.",
        "comparison": "FIFO against deadline-first on the same 9 synthetic build cases",
        "form": "table", "values_count": 4, "title": TITLE, "caption": " ".join(SOURCE_LINES),
        "encodings": [{"mark": "table"}], "accents": 1,
        "sources": [{"title": "policy-results.csv", "as_of": "2026-10-26",
                     "url": "https://github.com/RahilBhavan/x402-exception-desk/blob/main/artifacts/generated/policy-results.csv"}],
        "alt": alt, "sizes_checked": [f"{CANVAS}x{CANVAS}"], "measurement_basis": "canvas", "feed_width_viewed": True,
        "measured_by": "docs/gate-card/build_gate_card.py (firefox)", "min_label_px": min(sizes), "point_px": TITLE_PX,
        "contrast_min": round(contrast_min, 2), "title_lines": measured["title_lines"], "overflow": measured["overflow"],
        "system_version": "rahil-design 3.10.0 tokens", "export": f"{EXPORT}x{EXPORT}", "artifacts": report["sha256"],
    }
    (HERE / "brief.json").write_text(json.dumps(brief, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    for error in errors:
        print("ERROR", error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
