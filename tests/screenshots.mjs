// Screenshots for the README and docs, taken from the demo database (tests/demo.py: invented history only).
// Playwright setup is as in tests/phone.mjs. Start a demo server, then run this from Playwright's folder:
//
//   python3 -I tests/demo.py /tmp/demo.db
//   HISTORY_SEARCH_INDEX=/tmp/demo-index.db HISTORY_SEARCH_LOCAL=/dev/null CLAUDE_MEM_WORKER_PORT=9 \
//     python3 -I server.py --db /tmp/demo.db --port 37691 &
//   PLAYWRIGHT_BROWSERS_PATH=$PWD/browsers node <this repo>/tests/screenshots.mjs [base-url] [out-dir]
//
// Meaning is switched off in the shots (meaning=0): the demo has no worker to ask.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const { webkit, devices } = createRequire(process.cwd() + "/")("playwright");
const BASE = process.argv[2] || "http://localhost:37691";
const OUT = process.argv[3] || path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "docs", "img");
const settle = page => page.waitForTimeout(800);

const browser = await webkit.launch();
async function shot(name, hash, { phone = false, dark = false, expand = 0, height } = {}) {
  const ctx = await browser.newContext(phone ? { ...devices["iPhone 13"], colorScheme: dark ? "dark" : "light" }
    : { viewport: { width: 1100, height: height || 760 }, deviceScaleFactor: 2, colorScheme: dark ? "dark" : "light" });
  const page = await ctx.newPage();
  await page.goto(BASE + "/" + hash);
  await settle(page);
  const heads = await page.$$(".head");
  for (const h of heads.slice(0, expand)) await h.click();
  await settle(page);
  await page.screenshot({ path: path.join(OUT, name) });
  console.log("wrote", name);
  await ctx.close();
}

await shot("search.png", "#q=why+were+users+logged+out+on+staging&meaning=0", { expand: 1, height: 900 });
await shot("search-dark.png", "#q=clock+skew+token&meaning=0", { dark: true, expand: 1 });
await shot("session.png", "#session=demo-1&turn=1&hl=observation:1", { height: 900 });
await shot("grouped.png", "#group=1&meaning=0", { height: 900 });
await shot("phone.png", "#q=refresh+forecast&meaning=0", { phone: true, dark: true, expand: 1 });
await browser.close();
