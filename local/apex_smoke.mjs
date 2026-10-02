/**
 * Browser check of the local apex: the home page button, then the
 * viewer at /viewer/ with no portal header or footer, the
 * portal menu and About sheet, Esc and the hash, and
 * live region freshness.
 * Needs the local stack running.
 * Run: CHROME=chromium node local/apex_smoke.mjs [base URL]
 */

import { spawn } from "node:child_process";

const BASE = process.argv[2] || "http://localhost:8000";
const TIMEOUT_MS = 30000;

/**
 * Start headless Chrome and return it with its DevTools HTTP address.
 * @returns {Promise<{chrome: import("node:child_process").ChildProcess, devtools: string}>}
 */
function launchChrome() {
  const binary = process.env.CHROME || "google-chrome";
  const chrome = spawn(binary, ["--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=0", "about:blank"]);
  return new Promise((resolve, reject) => {
    chrome.on("error", reject);
    chrome.stderr.on("data", (chunk) => {
      const match = String(chunk).match(/DevTools listening on ws:\/\/([^/]+)\//);
      if (match) resolve({ chrome, devtools: `http://${match[1]}` });
    });
  });
}

/**
 * Open a page and return helpers to evaluate and send DevTools commands.
 * @param {string} devtools DevTools HTTP address
 * @param {string} url page to open
 * @returns {Promise<{evaluate: (expression: string) => Promise<any>, send: (method: string, params: object) => Promise<any>, close: () => void}>}
 */
async function openPage(devtools, url) {
  const target = await (await fetch(`${devtools}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve) => socket.addEventListener("open", resolve));
  const pending = new Map();
  let id = 0;
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    pending.get(message.id)?.(message.result);
    pending.delete(message.id);
  });
  const send = (method, params) => new Promise((resolve) => {
    pending.set(++id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true }))?.result?.value;
  return { evaluate, send, close: () => socket.close() };
}

/**
 * Poll an expression until it returns a truthy value or time runs out.
 * @param {(expression: string) => Promise<any>} evaluate
 * @param {string} expression
 * @param {string} what description for the failure message
 * @returns {Promise<any>}
 */
async function waitFor(evaluate, expression, what) {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`timed out waiting for ${what}`);
}

/**
 * Press Escape in the page.
 * @param {(method: string, params: object) => Promise<any>} send
 */
async function pressEscape(send) {
  const key = { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 };
  await send("Input.dispatchKeyEvent", { type: "keyDown", ...key });
  await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
}

/**
 * Check the portal menu deep link, Esc and hash clearing.
 * @param {{evaluate: Function, send: Function}} page
 */
async function checkMenu({ evaluate, send }) {
  await waitFor(evaluate, '!document.getElementById("portals-menu").hidden', "portal menu open from #portals");
  const links = await evaluate('[...document.querySelectorAll("#portals-menu a.apex-agency")].map((a) => a.host).join(",")');
  if (links.split(",").length !== 4) throw new Error(`agency links: ${links}`);
  await pressEscape(send);
  await waitFor(evaluate, 'document.getElementById("portals-menu").hidden && location.hash === "" && document.activeElement.id === "portals-button"', "Esc closes the menu, clears the hash, refocuses");
}

/**
 * Check the About sheet opens beside the map and closes on Esc.
 * @param {{evaluate: Function, send: Function}} page
 */
async function checkAbout({ evaluate, send }) {
  await evaluate('document.getElementById("about-button").click()');
  await waitFor(evaluate, 'document.getElementById("about").open && location.hash === "#about" && document.activeElement.id === "about-title"', "About sheet open with focus");
  const marks = await evaluate('(() => { const r = document.getElementById("about").getBoundingClientRect(); return [...document.querySelectorAll("#about .apex-partners img")].filter((i) => i.getBoundingClientRect().right <= r.right + 1).length; })()');
  if (marks !== 5) throw new Error(`partner marks inside the sheet: ${marks}`);
  await pressEscape(send);
  await waitFor(evaluate, '!document.getElementById("about").open && location.hash === ""', "Esc closes the About sheet");
}

/**
 * Check the map fills the page with no portal header or footer.
 * @param {(expression: string) => Promise<any>} evaluate
 */
async function checkLayout(evaluate) {
  const chrome = await evaluate('Boolean(document.querySelector(".site-header, .site-footer"))');
  if (chrome) throw new Error("portal header or footer is on the page");
  const full = await evaluate('(() => { const r = document.getElementById("map").getBoundingClientRect(); return r.width === innerWidth && r.height === innerHeight; })()');
  if (!full) throw new Error("map does not fill the window");
}

/**
 * Check that every region chip carries a live freshness level.
 * @param {(expression: string) => Promise<any>} evaluate
 */
async function checkRegions(evaluate) {
  await waitFor(evaluate, 'document.querySelectorAll("#regions .chip.ok, #regions .chip.late, #regions .chip.stale").length === 4', "four live region chips");
}

/**
 * The home page keeps the portal directory and links to the viewer.
 * @param {(expression: string) => Promise<any>} evaluate
 */
async function checkHome(evaluate) {
  await waitFor(evaluate, '[...document.querySelectorAll(".u-btn")].some((a) => a.textContent.trim() === "Go to UFFIS Viewer" && a.getAttribute("href") === "/viewer/") && document.getElementById("portals") && !document.getElementById("uffis-viewer")', "home page with the viewer button");
}

/**
 * French and Spanish via ?lang=: the home page, the viewer frame and
 * the viewer's JS text, then back to English.
 * @param {string} devtools DevTools HTTP address
 */
async function checkLanguages(devtools) {
  const home = await openPage(devtools, `${BASE}/?lang=fr`);
  await waitFor(home.evaluate, 'document.documentElement.lang === "fr" && [...document.querySelectorAll(".u-btn")].some((a) => a.textContent.trim() === "Ouvrir le visualiseur UFFIS")', "French home page");
  home.close();
  const viewer = await openPage(devtools, `${BASE}/viewer/?lang=es`);
  await waitFor(viewer.evaluate, 'document.documentElement.lang === "es" && [...document.querySelectorAll("legend")].some((l) => l.textContent === "Precipitación") && document.getElementById("about-button").textContent === "Acerca de"', "Spanish viewer frame and panel");
  await waitFor(viewer.evaluate, '(document.querySelector("#status .card .age")?.textContent || "").startsWith("Publicado") && [...document.querySelectorAll("#regions .chip")].some((c) => c.textContent.includes("Haití"))', "Spanish text from the viewer JS");
  viewer.close();
  const reset = await openPage(devtools, `${BASE}/?lang=en`);
  await waitFor(reset.evaluate, 'document.documentElement.lang === "en"', "back to English");
  reset.close();
}

const { chrome, devtools } = await launchChrome();
let failed = false;
try {
  const home = await openPage(devtools, `${BASE}/`);
  await checkHome(home.evaluate);
  home.close();
  const page = await openPage(devtools, `${BASE}/viewer/#portals`);
  await checkMenu(page);
  await checkAbout(page);
  await checkLayout(page.evaluate);
  await waitFor(page.evaluate, 'document.querySelector(".apex-home")?.getAttribute("href") === "/"', "back link to the home page");
  await checkRegions(page.evaluate);
  const regions = await page.evaluate('[...document.querySelectorAll("#regions .chip")].map((c) => c.textContent + " " + c.className.replace("chip ", "")).join(", ")');
  page.close();
  await checkLanguages(devtools);
  console.log(`apex smoke ok: home button, back link, full map, portal menu, About sheet, Esc, hash, French and Spanish; ${regions}`);
} catch (error) {
  failed = true;
  console.error(`apex smoke failed: ${error.message}`);
} finally {
  chrome.kill();
}
process.exit(failed ? 1 : 0);
