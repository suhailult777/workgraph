import { chromium } from "file:///C:/Users/suhai/milestonepay/web/node_modules/playwright/index.mjs";

const base = "http://127.0.0.1:8092";
const profile = "C:\\Users\\suhai\\workgraph\\probes\\wasm\\.profile";

const context = await chromium.launchPersistentContext(profile, {
  headless: true,
  executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  args: ["--no-sandbox"],
});

const page = await context.newPage();
page.on("console", (m) => console.log("console:", m.type(), m.text()));
page.on("pageerror", (e) => console.log("pageerror:", e.message));

await page.goto(base + "/probe.html", { waitUntil: "networkidle" });

const inMemory = await page.evaluate(() => window.runInMemory());
console.log("in-memory:", JSON.stringify(inMemory));

const first = await page.evaluate(() => window.runOpfs("open"));
console.log("opfs first:", JSON.stringify(first));

await page.reload({ waitUntil: "networkidle" });
const second = await page.evaluate(() => window.runOpfs("read"));
console.log("opfs after reload:", JSON.stringify(second));

await page.screenshot({ path: "C:\\Users\\suhai\\workgraph\\probes\\wasm\\probe.png" });
await context.close();
