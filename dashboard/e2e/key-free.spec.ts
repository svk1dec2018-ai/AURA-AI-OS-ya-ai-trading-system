import { test, expect } from "@playwright/test";

test("cockpit opens without keys and exposes full workstation", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("AURA PRIME", { exact: true })).toBeVisible();
  await expect(page.getByText("MT5 OFFLINE", { exact: true }).first()).toBeVisible();
  const health = await request.get("/api/health");
  expect((await health.json()).ok).toBe(true);
  const fleet = await request.get("/api/fleet/events");
  expect(fleet.status()).toBe(503);
  expect((await fleet.json()).ok).toBe(false);
  await expect(page.getByText("MetaTrader 5", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/desktop-cockpit.png", fullPage: true });
  await page.getByRole("button", { name: /AI Council/ }).click();
  await expect(page.getByText("Groq", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Research/ }).click();
  await page.getByRole("link", { name: /Open full workstation/ }).click();
  await expect(page.getByRole("button", { name: /Strategy Studio/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("owner token can be stored and cleared in the browser session", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /System/ }).click();
  await page.getByLabel("Owner token (if enabled in .env.local)").fill("test-session-token");
  await page.getByRole("button", { name: "Save for this session" }).click();
  expect(await page.evaluate(() => sessionStorage.getItem("aura-owner-token"))).toBe("test-session-token");
  await page.getByRole("button", { name: "Save for this session" }).click();
  expect(await page.evaluate(() => sessionStorage.getItem("aura-owner-token"))).toBeNull();
});

test("mobile cockpit stays visible and demo start is blocked without MT5", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByText("AURA PRIME", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "START DEMO", exact: true })).toBeVisible();
  await expect(page.getByText("MetaTrader 5", { exact: true })).toBeVisible();
  const start = await request.post("/api/start", { data: { max_symbols: 1, max_batches: 1 } });
  expect(start.status()).toBe(400);
  expect((await start.json()).ok).toBe(false);
  await page.screenshot({ path: "test-results/mobile-cockpit.png", fullPage: true });
});

test("strategy studio compiles the new setup for a chosen symbol without keys", async ({ page, request }) => {
  await page.goto("/workstation");
  await page.getByRole("button", { name: /Strategy Studio/ }).click();
  await expect(page.getByText("Strategy Factory + causal backtest · 14 setups")).toBeVisible();
  await page.getByLabel("Research symbol").fill("EURUSD");
  await page.getByLabel("Research timeframe").selectOption("15m");
  await page.getByRole("button", { name: /Supertrend continuation/ }).click();
  await expect(page.getByText(/Candidate built:/)).toBeVisible();
  const candidates = await (await request.get("/api/algo/candidates")).json();
  const candidate = candidates.items.find((item: any) => item.owner_name === "Supertrend continuation AURA Prime" && item.blueprint.market_scope.includes("EURUSD"));
  expect(candidate.algorithm.compilable).toBe(true);
  expect(candidate.blueprint.timeframe_scope).toEqual(["15m"]);
  expect(candidate.blueprint.parameters.minimum_confirmations).toBe(candidate.blueprint.confirmations.length);
  expect(candidate.live_approved).toBe(false);
  await expect(page.getByRole("button", { name: "Run EURUSD 15m causal backtest" })).toBeEnabled();
  await page.screenshot({ path: "test-results/strategy-studio.png", fullPage: true });
});
