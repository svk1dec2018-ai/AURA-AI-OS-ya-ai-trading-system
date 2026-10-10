import { test, expect } from '@playwright/test';

test.afterEach(async ({ request }) => { await request.post('/api/reset-kill', { data: {} }); });

test('all workstation views render on desktop and mobile without JS exceptions', async ({ page }) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const views = ['Overview', 'Markets', 'Live Charts', 'Opportunities', 'Trading Desk', 'Portfolio', 'AI Brain', 'Agent Debate', 'Risk Center', 'Performance', 'Research Lab', 'Learning', 'News / Macro', 'Trade Journal', 'Strategy Studio', 'All Features', 'Distributed Fleet', 'System Health', 'Owner / JARVIS'];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/workstation');
    for (const name of views) {
      await page.getByRole('button', { name: new RegExp(name) }).first().click();
      await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible();
    }
  }
  expect(errors).toEqual([]);
});

test('all 14 strategy buttons compile and broker backtests fail honestly offline', async ({ page, request }) => {
  test.setTimeout(90000);
  const options = await (await request.get('/api/algo/options')).json();
  expect(options.templates).toHaveLength(14);
  await page.goto('/workstation');
  await page.getByRole('button', { name: /Strategy Studio/ }).click();
  await page.getByLabel('Research symbol').fill('EURUSD');
  await page.getByLabel('Research timeframe').selectOption('30m');
  await page.getByLabel('Closed bars').fill('300');
  for (const template of options.templates) {
    const built = page.waitForResponse(r => r.url().endsWith('/api/algo/build') && r.request().method() === 'POST');
    await page.getByRole('button', { name: template.name }).click();
    expect((await built).status()).toBe(200);
    await expect(page.getByText(/Candidate built:/)).toBeVisible();
    const run = page.waitForResponse(r => r.url().endsWith('/api/backtest/run'));
    await page.getByRole('button', { name: 'Run EURUSD 30m causal backtest' }).click();
    const response = await run;
    expect(response.status()).toBe(400);
    expect((await response.json()).ok).toBe(false);
  }
  const candidates = await (await request.get('/api/algo/candidates')).json();
  for (const template of options.templates) {
    const candidate = candidates.items.find((item: any) => item.owner_name === template.name + ' AURA Prime' && item.blueprint.timeframe_scope.includes('30m'));
    expect(candidate.algorithm.compilable).toBe(true);
    expect(candidate.live_approved).toBe(false);
  }
});

test('runtime control buttons exercise actual start stop kill reset guards', async ({ page }) => {
  await page.goto('/workstation');
  await page.getByRole('button', { name: /Trading Desk/ }).click();
  for (const [name, route] of [['Start continuous DEMO', '/api/start'], ['Stop runtime', '/api/stop'], ['Emergency lock', '/api/kill']]) {
    const response = page.waitForResponse(r => r.url().endsWith(route) && r.request().method() === 'POST');
    await page.getByRole('button', { name, exact: true }).click();
    expect((await response).status()).toBe(route === '/api/start' ? 400 : 200);
  }
  await page.getByLabel('Symbol', { exact: true }).fill('EURUSD');
  for (const side of ['BUY', 'SELL']) {
    await page.getByLabel('Side', { exact: true }).selectOption(side);
    const result = page.waitForResponse(r => r.url().includes('/api/mt5/execution-check?'));
    await page.getByRole('button', { name: 'Check broker acceptance' }).click();
    expect((await result).status()).toBe(400);
    await expect(page.locator('.tool-error')).toBeVisible();
  }
  await page.getByRole('button', { name: /Owner \/ JARVIS/ }).click();
  const reset = page.waitForResponse(r => r.url().endsWith('/api/reset-kill'));
  await page.getByRole('button', { name: 'Reset local emergency lock' }).click();
  expect((await reset).status()).toBe(200);
});

test('public API inventory returns JSON and invalid routes and payloads fail', async ({ request }) => {
  for (const route of ['/api/health', '/api/status', '/api/capabilities', '/api/decisions', '/api/journal', '/api/learning', '/api/intelligence', '/api/security', '/api/algo/options', '/api/algo/candidates', '/api/chart/options', '/api/diagnostics', '/api/fleet/status', '/api/prime/status', '/api/prime/quotes', '/api/workspace', '/api/readiness']) {
    const response = await request.get(route);
    expect(response.status(), route).toBe(200);
    expect(response.headers()['content-type']).toContain('application/json');
    expect(await response.json()).toBeTruthy();
  }
  const missing = await request.get('/api/nonexistent-audit-route');
  expect(missing.status()).toBe(404);
  expect((await missing.json()).ok).toBe(false);
  const malformed = await request.post('/api/command', { data: 'not-json', headers: { 'Content-Type': 'application/json' } });
  expect(malformed.status()).toBe(400);
});

test('all six assistant examples submit and modal closes', async ({ page }) => {
  await page.goto('/workstation');
  await page.getByRole('button', { name: /Owner \/ JARVIS/ }).click();
  for (const name of ['Gold analyse karo', 'Aaj ka P&L dikhao', 'Why did you skip the last trade?', 'Agent debate explain karo', 'System health check', 'Latest opportunities batao']) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.getByPlaceholder('Ask AURA...')).toHaveValue(name);
    const result = page.waitForResponse(r => r.url().endsWith('/api/command'));
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    expect((await result).status()).toBe(200);
    await page.getByRole('button', { name: 'Close AURA assistant' }).click();
  }
});

test('cockpit navigation chart controls voice fallback and shortcuts work', async ({ page }) => {
  await page.goto('/');
  for (const name of ['AI Council', 'Risk', 'Research', 'System', 'Live Desk']) {
    await page.getByRole('button', { name: new RegExp(name) }).first().click();
  }
  await page.getByLabel('Chart symbol').fill('EURUSD');
  for (const tf of ['1m', '5m', '15m', '30m', '1h', '4h', '1d']) {
    const response = page.waitForResponse(r => r.url().includes('/api/chart?') && r.url().includes('timeframe=' + tf));
    await page.getByRole('button', { name: tf.toUpperCase(), exact: true }).click();
    expect((await response).status()).toBe(400);
  }
  await page.getByRole('button', { name: 'Retry MT5 connection' }).click();
  await page.keyboard.press('Control+k');
  await expect(page.getByPlaceholder('Ask AURA or type an owner command...')).toBeVisible();
  await page.getByRole('button', { name: /SPEAK/ }).click();
  await page.evaluate(() => { delete (window as any).SpeechRecognition; delete (window as any).webkitSpeechRecognition; });
  await page.getByRole('button', { name: '◉ VOICE' }).click();
  await expect(page.getByText(/Browser speech recognition is unavailable/)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByPlaceholder('Ask AURA or type an owner command...')).toHaveCount(0);
});

test('capability search and every state filter reflect the actual catalog', async ({ page, request }) => {
  const catalog = await (await request.get('/api/capabilities')).json();
  await page.goto('/workstation');
  await page.getByRole('button', { name: /All Features/ }).click();
  await page.getByPlaceholder('Search AURA capabilities...').fill('unlikely-nonexistent-capability');
  await expect(page.locator('.cap-cards article')).toHaveCount(0);
  await page.getByPlaceholder('Search AURA capabilities...').fill('');
  for (const state of ['all', 'ui_connected', 'backend_ready', 'partial', 'external_gate', 'pending', 'blocked']) {
    await page.locator('.cap-tools select').selectOption(state);
    const items = catalog.items || catalog.capabilities || [];
    await expect(page.locator('.cap-cards article')).toHaveCount(items.filter((item: any) => state === 'all' || item.status === state).length);
  }
});

test('all-market scan scope reaches backend without bypassing demo preflight', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Live Desk/ }).first().click();
  await page.getByLabel('MT5 scan scope').selectOption('0');
  const submitted = page.waitForRequest(r => r.url().endsWith('/api/start') && r.method() === 'POST');
  const response = page.waitForResponse(r => r.url().endsWith('/api/start'));
  await page.getByRole('button', { name: 'START DEMO', exact: true }).click();
  expect((await submitted).postDataJSON().max_symbols).toBe(0);
  expect((await response).status()).toBe(400);
  await page.goto('/workstation');
  await page.getByRole('button', { name: /Trading Desk/ }).click();
  await page.getByLabel('MT5 scan scope').selectOption('100');
  const workstation = page.waitForRequest(r => r.url().endsWith('/api/start') && r.method() === 'POST');
  await page.getByRole('button', { name: 'Start continuous DEMO' }).click();
  expect((await workstation).postDataJSON().max_symbols).toBe(100);
});
