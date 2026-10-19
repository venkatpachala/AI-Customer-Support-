/** Full UI/API regression against tests/browser_server.py (fake models, real persistence). */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const base = process.env.E2E_BASE_URL || "http://127.0.0.1:8080";
const policy = resolve("../artifacts/pilot-policy.pdf");
mkdirSync("screenshots", { recursive: true });
const browser = await chromium.launch({ headless: true });
const owner = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const errors = [];
const page = await owner.newPage();
page.on("pageerror", (error) => errors.push(error.message));
const results = [];
try {
  await page.goto(`${base}/enter`, { waitUntil: "networkidle" });
  await page.waitForLoadState("networkidle");
  await page.getByPlaceholder("Brand name").fill("Pilot store");
  await page.getByPlaceholder("Email", { exact: true }).fill(`browser-${Date.now()}@example.test`);
  await page.getByPlaceholder("Password", { exact: true }).fill("browser-only-password-123");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("Brand created. Keys are shown once.").waitFor();
  const me = await (await owner.request.get(`${base}/v1/me`)).json();
  assert.ok(me.tenant_id);
  results.push("UI signup creates authenticated backend tenant");

  await page.goto(`${base}/console/knowledge`, { waitUntil: "networkidle" });
  await page.locator('input[type="file"]').setInputFiles(policy);
  await page.getByText("pilot-policy.pdf", { exact: true }).waitFor();
  results.push("UI upload persists and activates searchable document");
  await page.screenshot({ path: "screenshots/knowledge-desktop.png", fullPage: true });

  const visitor = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const chat = await visitor.newPage();
  chat.on("pageerror", (error) => errors.push(error.message));
  await chat.goto(`${base}/w/${me.tenant_id}`, { waitUntil: "networkidle" });
  await chat.getByRole("textbox", { name: "Message", exact: true }).fill("What is the policy for photographs of damaged items?");
  await chat.getByRole("button", { name: "Send", exact: true }).click();
  await chat.getByText(/Sources: pilot-policy.pdf/).waitFor({ timeout: 60000 });
  results.push("Customer chat runs backend graph and cites uploaded source");
  await chat.screenshot({ path: "screenshots/widget-mobile.png", fullPage: true });

  await page.goto(`${base}/console/inbox`, { waitUntil: "networkidle" });
  const caseResponse = await owner.request.get(`${base}/v1/desk/cases`);
  const cases = await caseResponse.json();
  assert.equal(cases.items.length, 1);
  const caseId = cases.items[0].id;
  await page.goto(`${base}/console/inbox/${caseId}`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Take over", exact: true }).click();
  await page.getByRole("textbox", { name: "Reply as the floor" }).fill("A human agent is reviewing your request now.");
  await page.getByRole("button", { name: "Send reply", exact: true }).click();
  await chat.getByText("A human agent is reviewing your request now.", { exact: true }).waitFor({ timeout: 15000 });
  results.push("Operator reply is delivered to customer without invoking the AI");
  await page.screenshot({ path: "screenshots/operator-desktop.png", fullPage: true });

  await page.getByRole("button", { name: "Mark resolved", exact: true }).click();
  await page.getByText("Resolved by operator", { exact: true }).first().waitFor();
  const resolved = await (await owner.request.get(`${base}/v1/desk/cases/${caseId}`)).json();
  assert.equal(resolved.conversation.status, "resolved");
  results.push("Operator resolution persists");
  const stranger = await browser.newContext();
  const denied = await stranger.request.get(`${base}/v1/desk/cases/${caseId}`);
  assert.equal(denied.status(), 401);
  results.push("Unauthenticated case access denied");
  await stranger.close();
  assert.deepEqual(errors, []);
  await visitor.close();
  writeFileSync("screenshots/support-e2e.json", JSON.stringify({ passed: true, results, errors }, null, 2));
  console.log(JSON.stringify({ passed: true, results, errors }, null, 2));
} catch (error) {
  await page.screenshot({ path: "screenshots/e2e-failure.png", fullPage: true });
  console.error(JSON.stringify({ url: page.url(), errors, failure: String(error) }));
  throw error;
} finally {
  await browser.close();
}
