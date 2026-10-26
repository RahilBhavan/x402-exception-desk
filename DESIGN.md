# Design system: x402 Exception Desk post cards

This file governs the public post cards for this project (`docs/x-post-chart/`). It records the spec requested for the Thursday 2026-10-29 09:30 ET card. The build script and the card checker in `docs/x-post-chart/` enforce the rules marked "checked".

**Status: design review pending.** This spec is navy and red with Roboto Slab and Archivo. Rahil's canonical public system (`rahil-design` 3.3.1) is charcoal, white and yellow with Anton and IBM Plex Sans. The two conflict. The navy and red look was already merged into this repository in #9 and #10, but no recorded decision from Rahil makes it the system for the Thursday post. Until Rahil confirms it, or asks for a rebuild in `rahil-design`, treat the card as a review draft. Passing CI or building the PNGs does not approve it.

## Principles

1. **The title is the takeaway.** It states the finding as a sentence, not a topic. Current card: "No queue rule wins every objective."
2. **One highlight.** Navy carries everything. Red marks only the winning values and never decorates.
3. **Say what the data is.** Every card says "Synthetic data", gives the scenario count and defines any metric a reader may not know.
4. **Every number traces to a file.** Values come from `artifacts/generated/scenario-sweep-summary.json` and are formatted to one decimal place. Nothing is typed by hand.
5. **Text survives a phone feed.** Nothing is smaller than 26px at the 1024px design width.

## Colour

| Role | Value | Use | Contrast on white |
| --- | --- | --- | --- |
| Navy | `#0b1f4d` | All text, rules, bold winning values | 15.9:1 |
| Red | `#d3202f` | Underline under winning values only | 5.2:1 |
| White | `#ffffff` | Card background | |

Red is never used as text colour on navy (3.0:1) and never as a second series. No other hues. Meaning never depends on colour alone: winning cells are also bold, so the card reads in greyscale.

## Type

| Role | Family | Weight | Size (1024px wide) |
| --- | --- | --- | --- |
| Title | Roboto Slab (Apache 2.0) | 700 | 44px landscape, 68px square |
| Body, labels, footer | Archivo (SIL OFL) | 400, 500, 700 | 26px minimum |
| Table values | Archivo, tabular figures | 400, winners 800 | 30px landscape, 40px square |

Fonts ship in `docs/x-post-chart/fonts/` with their licences. The build fails if either font does not load. All text is at least 26px at 1024px wide (checked).

## Formats

| Format | CSS size | PNG size | Use |
| --- | --- | --- | --- |
| Landscape | 1024 x 640 | 2048 x 1280 | Single image in a post |
| Square | 1024 x 1024 | 2048 x 2048 | Multi-image posts and feeds that crop to square |

PNGs render at 2x for sharpness. Both formats carry identical content, and only spacing and type size change between them. Padding is 36px at the sides in landscape and 56px in the square.

## Layout of a table card

1. Title (Roboto Slab, at most two lines).
2. Subtitle: "Synthetic data: ..." with the scenario count, then the sweep definition.
3. Table: objective rows, policy columns, rules between rows, no vertical rules, no fill.
4. Footer note defining the metrics.
5. Source line: repository, "Data as of", date and short commit SHA of the data file.

The footer always ends at the bottom padding (checked).

## Accessibility and alt text

Alt text is generated from the same rows as the image, so it cannot drift from the card. It names the title, the data type, every value, each winner and how winners are marked. It stays under X's 1,000-character limit (checked).

## Checks before a card goes anywhere

- `python3 docs/x-post-chart/build_chart.py` passes: font loaded, text >= 26px, nothing outside the canvas, footer on the bottom padding, PNG dimensions exact.
- The post text and the card make the same claim and use the same numbers.
- The card is viewed at phone and feed size.
- Rahil confirms the palette and type, or the card is rebuilt in his system.

## Not covered

This file does not cover the private Orbit hub, client work or website pages. It does not authorise posting.
