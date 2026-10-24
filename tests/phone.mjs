// iPhone checks in real WebKit (Safari's engine), via Playwright's "iPhone 13" profile, against the
// running server. Playwright lives outside the repo; run from the folder it's installed in:
//
//   cd <scratch dir> && npm i playwright@1.49.1 && PLAYWRIGHT_BROWSERS_PATH=$PWD/browsers npx playwright install webkit
//   PLAYWRIGHT_BROWSERS_PATH=$PWD/browsers node <this repo>/tests/phone.mjs [base-url, default http://localhost:37690]
//
// Checks: nothing wider than the screen (all results expanded), inputs >= 16px (else iOS Safari zooms
// in on tap, which WebKit here doesn't reproduce), the growing search box and ✕, the session view and
// back, grouping. Prints PASS/FAIL per check and exits 1 on any failure.
import { createRequire } from "node:module";

const { webkit, devices } = createRequire(process.cwd() + "/")("playwright");
const BASE = process.argv[2] || "http://localhost:37690";
let failed = 0;
const check = (name, ok, detail = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  " + detail : ""}`); };

const browser = await webkit.launch();
const page = await (await browser.newContext({ ...devices["iPhone 13"] })).newPage();
const errors = []; page.on("pageerror", e => errors.push(String(e)));
const width = () => page.evaluate(() => document.documentElement.scrollWidth);
const settle = (ms = 2500) => page.waitForTimeout(ms);

// 1. Width with every result expanded, in each mode.
for (const hash of ["#size=100", "#q=login+server&size=100", "#mode=conversation&size=100", "#q=api+config+path&mode=notes&size=100"]) {
  await page.goto(BASE + "/" + hash); await settle();
  await page.$$eval(".head", hs => hs.forEach(h => h.click())); await settle(300);
  const w = await width();
  check(`fits 390px ${hash}`, w <= 390, `scrollWidth=${w}`);
}

// 2. Inputs at least 16px.
const small = await page.evaluate(() => [...document.querySelectorAll("textarea, input, select")]
  .filter(e => parseFloat(getComputedStyle(e).fontSize) < 16).map(e => e.id || e.tagName));
check("inputs >= 16px (no iOS zoom on tap)", small.length === 0, small.join(" "));

// 3. Search box grows, Return searches once, ✕ clears.
await page.goto(BASE + "/"); await settle(1500);
const finds = []; page.on("request", r => { if (r.url().includes("/api/find")) finds.push(r.url()); });
const h0 = await page.$eval("#q", q => q.getBoundingClientRect().height);
await page.tap("#q");
await page.keyboard.type("where did we talk about the login page breaking for some users after the database migration last week", { delay: 3 });
const h1 = await page.$eval("#q", q => q.getBoundingClientRect().height);
check("search box grows for a long question", h1 > h0, `${Math.round(h0)} -> ${Math.round(h1)}px`);
finds.length = 0; await page.keyboard.press("Enter"); await settle(1500);
const v = await page.$eval("#q", q => q.value);
check("Return searches once, no newline", finds.length === 1 && !v.includes("\n"), `searches=${finds.length}`);
await page.tap("#clear"); await settle(800);
const cleared = await page.evaluate(() => ({ v: document.getElementById("q").value, hidden: document.getElementById("clear").hidden }));
check("✕ clears the box and hides itself", cleared.v === "" && cleared.hidden);

// 4. Session view from a result, then back.
await page.goto(BASE + "/#q=why+did+the+login+break"); await settle();
await page.tap(".item .head"); await settle(200);
await page.tap(".item.open .ctx"); await settle(1500);
const s = await page.evaluate(() => ({ on: document.body.classList.contains("in-session"), hit: !!document.querySelector(".hit"),
  turns: document.querySelectorAll(".turn").length }));
check("Show in session opens the session at the hit", s.on && s.hit && s.turns > 0, JSON.stringify(s));
check("session view fits 390px", (await width()) <= 390);
await page.tap("#back"); await settle(2000);
const back = await page.evaluate(() => ({ on: document.body.classList.contains("in-session"), q: document.getElementById("q").value }));
check("← Results returns to the same search", !back.on && back.q === "why did the login break");

// 5. Group by session.
await page.tap("#filtersBtn"); await page.tap("#group"); await settle();
const groups = await page.evaluate(() => ({ n: document.querySelectorAll(".group").length, hash: location.hash }));
check("Group by session shows session cards", groups.n > 0 && groups.hash.includes("group=1"), `${groups.n} cards`);
check("grouped results fit 390px", (await width()) <= 390);

check("no script errors", errors.length === 0, errors.join(" | "));
await browser.close();
process.exit(failed ? 1 : 0);
