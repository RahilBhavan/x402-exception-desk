"""Build results/x-cards/thu29-am-x402-gate/card.png and alt.txt from artifacts/generated/policy-results.csv.

The request fixed the 3.3.2 look: 1080x1080, charcoal ground, off-white text, Anton for the title and hero
number, IBM Plex Sans for everything else, yellow only on the -64% marker and the failed-gate "6" box.
Fonts come from the rahil-design bundle (RAHIL_FONTS overrides the path). Needs Playwright (PLAYWRIGHT_NODE_MODULES).
"""
import csv
import html
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results/x-cards/thu29-am-x402-gate"
FONTS = Path(os.environ.get("RAHIL_FONTS", "/home/rahil/.t3/projects/main/.agents/skills/rahil-design/assets/fonts"))
COMMIT = "f05dbe8"
GATE_REDUCTION = 0.15
USDC_ATOMIC = 1e6

rows = {r["policy"]: r for r in csv.DictReader(open(ROOT / "artifacts/generated/policy-results.csv"))}
fifo, deadline = rows["fifo"], rows["deadline_first"]
fifo_overdue, deadline_overdue = int(fifo["overdue_count"]), int(deadline["overdue_count"])
fifo_min = float(fifo["value_weighted_overdue_minutes"]) / USDC_ATOMIC
deadline_min = float(deadline["value_weighted_overdue_minutes"]) / USDC_ATOMIC
change = round((deadline_min / fifo_min - 1) * 100)
limit = int(fifo_overdue * (1 - GATE_REDUCTION))  # 6 * 0.85 = 5.1 -> 5 or fewer
assert fifo["data_classification"] == deadline["data_classification"] == "synthetic"
assert fifo_overdue == deadline_overdue == 6 and deadline_overdue > limit, "gate must have failed"
assert change == -64 and limit == 5

T = {
    "title": "LESS OVERDUE TIME. GATE STILL FAILED.",
    "sub": "Synthetic data · 9 actionable build cases, not held-out",
    "hero_caption": "overdue cases, same as FIFO",
    "fifo": f"Value-weighted overdue time (USDC-minutes), FIFO: {fifo_min:,.1f}",
    "deadline": f"Value-weighted overdue time (USDC-minutes), deadline-first: {deadline_min:,.1f}",
    "change": f"−{abs(change)}%",
    "box": f"Overdue cases, deadline-first: {deadline_overdue}",
    "gate": f"Gate, set before the run: ≥15% fewer than FIFO's {fifo_overdue}, so {limit} or fewer",
    "footer": f"Source: x402-exception-desk README, commit {COMMIT} · Oct 2026",
}
HERO = str(fifo_overdue)
def e(text):
    return html.escape(text).replace('(USDC-minutes),', '<span class="k">(USDC-minutes),</span>')

PAGE = f"""<!doctype html><html lang="en"><meta charset="utf-8"><style>
@font-face{{font-family:Anton;src:url("file://{FONTS}/Anton-Regular.ttf")}}
@font-face{{font-family:"IBM Plex Sans";font-weight:400;src:url("file://{FONTS}/IBMPlexSans-Regular.ttf")}}
@font-face{{font-family:"IBM Plex Sans";font-weight:600;src:url("file://{FONTS}/IBMPlexSans-SemiBold.ttf")}}
*{{box-sizing:border-box;margin:0}}
body{{width:1080px;height:1080px;background:#111214;color:#F5F5EF;font:400 36px/1.22 "IBM Plex Sans";overflow:hidden}}
.card{{height:1080px;padding:44px 48px 40px;display:flex;flex-direction:column}}
h1{{font:400 104px/1.02 Anton;letter-spacing:.01em}}
.sub{{margin-top:18px;font-size:34px;line-height:1.2}}
.hero{{display:flex;align-items:center;gap:32px;margin-top:14px}}
.hero .n{{font:400 190px/1 Anton}}
.hero .c{{font-size:44px;line-height:1.15}}
.row{{margin-top:14px;display:flex;justify-content:space-between;align-items:center;gap:24px}}
.k{{white-space:nowrap}}
.row p{{flex:1;text-wrap:balance}} .row b,.box b{{font-weight:600}}
.chg{{font-weight:600;font-size:72px;line-height:1;color:#FFE500;white-space:nowrap}}
.box{{margin-top:22px;background:#FFE500;color:#111214;padding:22px 28px}}
.box .t{{font-size:42px;line-height:1.15}}
.box .g{{margin-top:8px;text-wrap:balance;font-size:34px;line-height:1.2}}
footer{{margin-top:auto;white-space:nowrap;font-size:32px;line-height:1.2}}
</style><body><main class="card">
<h1>{e(T['title']).replace('. ', '.<br>', 1)}</h1>
<p class="sub">{e(T['sub'])}</p>
<div class="hero"><span class="n">{HERO}</span><span class="c">{e(T['hero_caption'])}</span></div>
<div class="row"><p>{e(T['fifo'])}</p></div>
<div class="row"><p>{e(T['deadline'])}</p><span class="chg">{e(T['change'])}</span></div>
<div class="box"><p class="t"><b>{e(T['box'])}</b></p><p class="g">{e(T['gate'])}</p></div>
<footer>{e(T['footer'])}</footer>
</main></body></html>"""

# alt text: the card's text in reading order, one item per line
ALT = [T["title"], T["sub"], HERO, T["hero_caption"], T["fifo"], T["deadline"], T["change"], T["box"], T["gate"], T["footer"]]

OUT.mkdir(parents=True, exist_ok=True)
page = OUT / "card.html"
page.write_text(PAGE)
(OUT / "alt.txt").write_text("\n".join(ALT) + "\n")
try:
    subprocess.run(["node", str(ROOT / "work/render_gate_card.cjs"), str(page), str(OUT / "card.png")], check=True)
finally:
    page.unlink()
