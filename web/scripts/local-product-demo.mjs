/** Interactive local demo. Uses the running backend and its configured model. */
import { chromium } from "playwright";
import { randomBytes } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const base = process.env.E2E_BASE_URL || "http://127.0.0.1:8080";
if (!new Set(["127.0.0.1", "localhost"]).has(new URL(base).hostname)) {
  throw new Error("Interactive demo must target a local development server.");
}
const artifacts = resolve("../artifacts");
mkdirSync(artifacts, { recursive: true });
const email = `venkat-demo-${Date.now()}@example.test`;
const password = randomBytes(18).toString("base64url");
const browser = await chromium.launch({ headless: false });
const operator = await browser.newContext({ viewport: { width: 1366, height: 850 } });
const desk = await operator.newPage();
const errors = [];
desk.on("pageerror", (error) => errors.push(error.message));
try {
  await desk.goto(`${base}/enter`, { waitUntil: "networkidle" });
  await desk.getByPlaceholder("Brand name").fill("Venkat Product Demo");
  await desk.getByPlaceholder("Email", { exact: true }).fill(email);
  await desk.getByPlaceholder("Password", { exact: true }).fill(password);
  await desk.getByRole("button", { name: "Create", exact: true }).click();
  await desk.getByText("Brand created. Keys are shown once.").waitFor();
  const identityResponse = await operator.request.get(`${base}/v1/me`);
  if (!identityResponse.ok()) throw new Error("Owner session did not authenticate");
  const me = await identityResponse.json();
  writeFileSync(resolve(artifacts, "local-product-demo-account.json"), JSON.stringify({
    email, password, tenant_id: me.tenant_id, console_url: `${base}/console`,
    widget_url: `${base}/w/${me.tenant_id}`,
    warning: "Local synthetic account only. Do not publish this file.",
  }, null, 2));
  await desk.goto(`${base}/console/knowledge`, { waitUntil: "networkidle" });
  await desk.locator('input[type="file"]').setInputFiles(resolve(artifacts, "pilot-policy.pdf"));
  await desk.getByText("pilot-policy.pdf", { exact: true }).waitFor();
  console.log("Demo brand created and policy uploaded.");

  const customer = await browser.newContext({ viewport: { width: 440, height: 850 } });
  const chat = await customer.newPage();
  chat.on("pageerror", (error) => errors.push(error.message));
  await chat.goto(`${base}/w/${me.tenant_id}`, { waitUntil: "networkidle" });
  await chat.getByRole("textbox", { name: "Message", exact: true }).fill("What is the policy for photographs of damaged items?");
  await chat.getByRole("button", { name: "Send", exact: true }).click();
  await chat.getByText(/Sources: pilot-policy.pdf/).waitFor({ timeout: 90000 });
  console.log("Customer received a cited answer from the running model.");
  const casesResponse = await operator.request.get(`${base}/v1/desk/cases`);
  const cases = await casesResponse.json();
  const caseId = cases.items[0]?.id;
  if (!caseId) throw new Error("Customer conversation did not appear in inbox");
  await desk.goto(`${base}/console/inbox/${caseId}`, { waitUntil: "networkidle" });
  await desk.getByRole("button", { name: "Take over", exact: true }).click();
  await desk.getByRole("textbox", { name: "Reply as the floor" }).fill("Hello! This is a human support reply from your operator desk. You can test both windows now.");
  await desk.getByRole("button", { name: "Send reply", exact: true }).click();
  await chat.getByText("Hello! This is a human support reply from your operator desk. You can test both windows now.", { exact: true }).waitFor({ timeout: 15000 });
  await desk.getByRole("button", { name: "Return to AI", exact: true }).click();
  await desk.goto(`${base}/console/inbox/${caseId}`, { waitUntil: "networkidle" });
  await desk.screenshot({ path: resolve(artifacts, "product-demo-desk.png"), fullPage: true });
  await chat.screenshot({ path: resolve(artifacts, "product-demo-chat.png"), fullPage: true });
  const result = { ready: true, brand: "Venkat Product Demo", case_id: caseId,
    tenant_id: me.tenant_id, console_url: desk.url(), widget_url: chat.url(), errors };
  writeFileSync(resolve(artifacts, "local-product-demo-result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  await desk.bringToFront();
} catch (error) {
  await desk.screenshot({ path: resolve(artifacts, "product-demo-error.png"), fullPage: true }).catch(() => {});
  console.error("Demo setup failed:", error.message);
  console.log("The browser is left open for inspection. Local credentials, if created, are in artifacts/local-product-demo-account.json.");
}
// Keep both authenticated windows available until the user closes the browser.
await new Promise((resolve) => browser.once("disconnected", resolve));
