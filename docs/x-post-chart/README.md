# Scenario sweep chart for the X post

`scenario-sweep-landscape.png` (1024x640 at 2x) and `scenario-sweep-square.png` (1024x1024 at 2x) show who wins each objective in the 3,600-scenario sweep. `alt-text.txt` is the image description.

Every number is read from `artifacts/generated/scenario-sweep-summary.json` and formatted to one decimal place. The footer date and short SHA come from the last commit that changed that file.

Design (see `DESIGN.md` at the repository root): navy and red on white, Roboto Slab titles (Apache 2.0) and Archivo body text (SIL OFL), all text at least 26px at 1024px wide. Winning cells are bold navy with a red underline. The fonts and licenses are in `fonts/`.

Rebuild after the sweep file changes:

```
npm install playwright && npx playwright install firefox
python3 docs/x-post-chart/build_chart.py
```

Set `PLAYWRIGHT_NODE_MODULES` if Node cannot find Playwright and `BROWSER` to `chromium` or `webkit` to change the engine. `render.cjs` fails the build if any text is under 26px, text leaves the canvas, a font is missing, or the content does not reach the bottom padding.

These files are outside the release package, so they do not change the release ZIP checksum.
