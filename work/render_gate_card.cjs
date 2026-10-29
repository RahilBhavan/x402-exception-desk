// Usage: node render_gate_card.cjs <page.html> <out.png>
// Renders at 1080x1080 (scale 1) and fails if a font is missing, any family other than Anton / IBM Plex Sans
// draws text, text is under 32px (about 10.7px on a 360px feed), or anything leaves the canvas or runs past the bottom margin. Overlaps are checked by eye.
const { firefox } = require("playwright");

(async () => {
  const [pagePath, out] = process.argv.slice(2);
  const browser = await firefox.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto("file://" + pagePath);
  await page.evaluate(() => document.fonts.ready);
  const problems = await page.evaluate(() => {
    const found = [];
    for (const f of ['400 16px Anton', '400 16px "IBM Plex Sans"', '600 16px "IBM Plex Sans"'])
      if (!document.fonts.check(f)) found.push("font not loaded: " + f);
    const used = new Set();
    const boxes = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!n.textContent.trim()) continue;
      const cs = getComputedStyle(n.parentElement);
      used.add(cs.fontFamily.replace(/"/g, ""));
      const title = n.textContent.trim().slice(0, 30);
      if (parseFloat(cs.fontSize) < 32) found.push(`text under 32px: ${title}`);
      const r = document.createRange(); r.selectNodeContents(n);
      const b = r.getBoundingClientRect();
      if (b.left < 40 || b.right > 1040 || b.bottom > 1048) found.push(`text outside safe area: ${title} ${JSON.stringify(b)}`);
      boxes.push({ title, b });
    }
    for (const f of used) if (!["Anton", "IBM Plex Sans"].includes(f)) found.push("other font family: " + f);
    const foot = document.querySelector("footer").getBoundingClientRect();
    const box = document.querySelector(".box").getBoundingClientRect();
    found.push(`INFO box bottom ${box.bottom}, footer top ${foot.top}, footer bottom ${foot.bottom}`);
    return found;
  });
  for (const p of problems) console.log(p);
  await page.screenshot({ path: out });
  await browser.close();
  if (problems.some((p) => !p.startsWith("INFO"))) process.exit(1);
})();
