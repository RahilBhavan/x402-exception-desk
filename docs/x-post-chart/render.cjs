// Usage: node render.cjs <page.html> <out.png> <width> <height> <scale>
// Renders the page at the given CSS size and device scale, after checking it: every text node is at least
// MIN_TEXT_PX, nothing overflows the canvas, and the content reaches the bottom edge. BROWSER picks the
// Playwright engine (default firefox); KEEP_FAILED=1 saves the image even when a check fails.
const { firefox, chromium, webkit } = require("playwright");

const MIN_TEXT_PX = 26;

async function main() {
  const [page_path, out, width, height, scale] = process.argv.slice(2);
  const engine = { firefox, chromium, webkit }[process.env.BROWSER || "firefox"];
  const browser = await engine.launch();
  const page = await browser.newPage({
    viewport: { width: +width, height: +height },
    deviceScaleFactor: +scale,
  });
  await page.goto("file://" + page_path);
  await page.evaluate(() => document.fonts.ready);
  const problems = await page.evaluate(
    ({ min, width, height }) => {
      const found = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent.trim()) continue;
        const el = node.parentElement;
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size < min) found.push(`text under ${min}px (${size}): ${node.textContent.trim()}`);
        const range = document.createRange();
        range.selectNodeContents(node);
        const box = range.getBoundingClientRect();
        if (box.left < 0 || box.right > width || box.top < 0 || box.bottom > height) {
          found.push(`text outside canvas: ${node.textContent.trim()}`);
        }
      }
      const families = ["Roboto Slab", "Archivo"];
      for (const family of families) {
        if (!document.fonts.check(`16px "${family}"`)) found.push(`font not loaded: ${family}`);
      }
      const footer = document.querySelector("footer").getBoundingClientRect();
      const pad = parseFloat(getComputedStyle(document.querySelector(".card")).paddingBottom);
      if (Math.abs(footer.bottom - (height - pad)) > 1) found.push(`content does not reach the bottom padding: ${footer.bottom}`);
      return found;
    },
    { min: MIN_TEXT_PX, width: +width, height: +height },
  );
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exitCode = 1;
  }
  if (!problems.length || process.env.KEEP_FAILED) await page.screenshot({ path: out });
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
