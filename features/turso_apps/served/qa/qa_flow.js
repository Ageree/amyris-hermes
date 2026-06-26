// Playwright QA: drive the Turso-backed habit tracker AS A REAL USER, recording
// a video + key screenshots. Proves the persistence round-trips through Turso by
// reloading the page and confirming the data survives (it lives in the DB, not
// localStorage — the page has no localStorage at all).
//
// Run (playwright resolvable via NODE_PATH; server already up on APP_URL):
//   APP_URL=http://127.0.0.1:8771 \
//   NODE_PATH=/path/to/pw/node_modules \
//   node features/turso_apps/served/qa/qa_flow.js
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const APP_URL = process.env.APP_URL || "http://127.0.0.1:8771";
const OUT_DIR = path.resolve(__dirname);
const SHOTS = path.join(OUT_DIR, "shots");
const VIDEO_DIR = path.join(OUT_DIR, "video");

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.mkdirSync(VIDEO_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 900, height: 820 },
    recordVideo: { dir: VIDEO_DIR, size: { width: 900, height: 820 } },
    locale: "ru-RU",
  });
  const page = await context.newPage();

  // 1) open the app — empty state
  await page.goto(APP_URL, { waitUntil: "networkidle" });
  await page.waitForSelector("h1");
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOTS, "01-empty.png") });

  // 2) add first habit
  await page.fill("#title", "пить воду");
  await page.waitForTimeout(400);
  await page.click(".add-btn");
  await page.waitForSelector("li .habit-title");
  await page.waitForTimeout(500);

  // add a second habit so the list looks real
  await page.fill("#title", "читать 20 минут");
  await page.waitForTimeout(300);
  await page.click(".add-btn");
  await page.waitForFunction(() => document.querySelectorAll("li").length >= 2);
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, "02-added.png") });

  // 3) mark "пить воду" done today — find its row, click its check button
  const waterRow = page.locator("li", { hasText: "пить воду" });
  await waterRow.locator(".check-btn").click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll("li")].some(
      (li) => li.textContent.includes("пить воду") && li.querySelector(".check-btn.done")
    )
  );
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(SHOTS, "03-checked.png") });

  // 4) confirm there is NO localStorage backing (so persistence can only be Turso)
  const lsKeys = await page.evaluate(() => Object.keys(window.localStorage));

  // 5) RELOAD — the only source of truth is the server -> Turso DB
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector("li .habit-title");
  await page.waitForTimeout(800);

  // assert both habits survived the reload AND "пить воду" is still done
  const state = await page.evaluate(() => {
    const items = [...document.querySelectorAll("li")].map((li) => ({
      title: li.querySelector(".habit-title")?.textContent || "",
      meta: li.querySelector(".habit-meta")?.textContent || "",
      done: !!li.querySelector(".check-btn.done"),
    }));
    return items;
  });
  await page.screenshot({ path: path.join(SHOTS, "04-after-reload.png") });

  const water = state.find((s) => s.title === "пить воду");
  const read = state.find((s) => s.title === "читать 20 минут");
  const ok =
    state.length === 2 &&
    water && water.done === true && water.meta.includes("1") &&
    read && read.done === false &&
    lsKeys.length === 0;

  // finalize the video
  const videoHandle = page.video();
  await context.close();
  await browser.close();

  let videoPath = null;
  if (videoHandle) videoPath = await videoHandle.path();

  const report = {
    pass: ok,
    localStorageKeys: lsKeys,
    stateAfterReload: state,
    videoPath,
    screenshots: ["01-empty.png", "02-added.png", "03-checked.png", "04-after-reload.png"].map((f) =>
      path.join(SHOTS, f)
    ),
  };
  console.log(JSON.stringify(report, null, 2));
  if (!ok) process.exit(1);
}

main().catch((e) => {
  console.error("QA FAILED:", e);
  process.exit(2);
});
