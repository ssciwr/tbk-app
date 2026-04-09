import { expect, test } from '@playwright/test';

const TINY_PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMBAAImfukAAAAASUVORK5CYII=';

test('login flow stores token and redirects to patient data stage', async ({ page }) => {
  await page.route('**/api/auth/token', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'token-123', token_type: 'bearer', expires_in: 3600 })
    });
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  await page.goto('/login');
  await page.getByLabel('Password').fill('secret');
  await page.getByRole('button', { name: 'Login' }).click();

  await expect(page).toHaveURL(/\/patient-data$/);
  await expect(page.getByText('Patient Data & QR Scan')).toBeVisible();
});

test('patient data stage allows fast-track submission with QR only', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let createCalls = 0;
  await page.route('**/api/cases', async (route, request) => {
    if (request.method() !== 'POST') {
      await route.fallback();
      return;
    }

    createCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ case_id: 99 })
    });
  });

  await page.route('**/api/cases/pending-image', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cases: [] }) });
  });

  await page.goto('/patient-data');
  await page.getByLabel('QR content').fill('qr-fast-track');
  await page.getByRole('button', { name: 'Save Patient Data' }).click();

  await expect.poll(() => createCalls).toBe(1);
  await expect(page).toHaveURL(/\/camera$/);
});

test('patient data stage only creates one case while save is in flight', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let createCalls = 0;
  let releaseCreate: (() => void) | undefined;
  const createBlocked = new Promise<void>((resolve) => {
    releaseCreate = resolve;
  });

  await page.route('**/api/cases', async (route, request) => {
    if (request.method() !== 'POST') {
      await route.fallback();
      return;
    }

    createCalls += 1;
    await createBlocked;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ case_id: 42 })
    });
  });

  await page.route('**/api/cases/pending-image', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cases: [] }) });
  });

  await page.goto('/patient-data');
  await page.getByLabel('Child name').fill('Ada');
  await page.getByLabel('Animal name').fill('Teddy');
  await page.getByLabel('QR content').fill('qr-123');

  const submitButton = page.getByRole('button', { name: /Save Patient Data|Saving patient data\.\.\./ });
  await page.locator('form').evaluate((form) => {
    (form as HTMLFormElement).requestSubmit();
    (form as HTMLFormElement).requestSubmit();
  });

  await expect(submitButton).toBeDisabled();
  await expect.poll(() => createCalls).toBe(1);

  releaseCreate?.();
  await expect(page).toHaveURL(/\/camera$/);
});

test('results page supports confirm decision', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let pendingCalls = 0;
  await page.route('**/api/review/pending', async (route) => {
    pendingCalls += 1;
    const body =
      pendingCalls === 1
        ? {
            cases: [
              {
                case_id: 1,
                metadata: {
                  child_name: 'Ada',
                  animal_name: 'Teddy',
                  broken_bone: false
                },
                original_url: TINY_PNG,
                result_urls: [TINY_PNG, TINY_PNG],
                results_per_image: 2
              }
            ]
          }
        : { cases: [] };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.route('**/api/review/1/decision', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success' }) });
  });
  await page.route('**/api/fracture/pending', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cases: [] }) });
  });

  await page.goto('/review');
  await expect(page.getByText('Case #1')).toBeVisible();

  await page.getByRole('button', { name: 'Accept' }).first().click();
  await expect(page).toHaveURL(/\/fracture$/);
});

test('review page sends edited animal hint with retry', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let pendingCalls = 0;
  await page.route('**/api/review/pending', async (route) => {
    pendingCalls += 1;
    const body =
      pendingCalls === 1
        ? {
            cases: [
              {
                case_id: 1,
                metadata: {
                  child_name: 'Ada',
                  animal_name: 'Teddy',
                  animal_type: '',
                  broken_bone: false
                },
                original_url: TINY_PNG,
                result_urls: [TINY_PNG],
                results_per_image: 1
              }
            ]
          }
        : { cases: [] };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  let retryPayload: { action?: string; animal_type?: string | null } | null = null;
  await page.route('**/api/review/1/decision', async (route, request) => {
    retryPayload = JSON.parse(request.postData() ?? '{}') as { action?: string; animal_type?: string | null };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success' }) });
  });

  await page.goto('/review');
  await page.getByLabel('Animal hint for case 1').fill('  red fox  ');
  await page.getByRole('button', { name: 'Retry generation' }).click();

  await expect.poll(() => retryPayload?.action).toBe('retry');
  await expect.poll(() => retryPayload?.animal_type).toBe('red fox');
  await expect(page.getByText('Case 1: retry applied.')).toBeVisible();
});

test('results page resolves relative protected image URLs in same-origin mode', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let originalFetches = 0;
  let xrayFetches = 0;

  await page.route('**/api/carousel', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            case_id: 3,
            metadata: {
              child_name: 'Ada',
              animal_name: 'Bunny',
              qr_content: 'qr-3',
              broken_bone: false
            },
            original_url: '/api/carousel/0/original',
            xray_url: '/api/carousel/0/xray',
            approved_at: '2026-04-09T10:00:00Z'
          }
        ],
        max_items: 10,
        autoplay_interval_seconds: 10
      })
    });
  });

  await page.route('**/api/carousel/0/original', async (route) => {
    originalFetches += 1;
    await route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(TINY_PNG.split(',')[1], 'base64') });
  });

  await page.route('**/api/carousel/0/xray', async (route) => {
    xrayFetches += 1;
    await route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(TINY_PNG.split(',')[1], 'base64') });
  });

  await page.goto('/results');

  await expect(page.getByText('Case: #3')).toBeVisible();
  await expect.poll(() => originalFetches).toBe(1);
  await expect.poll(() => xrayFetches).toBe(1);
  await expect(page.getByRole('img', { name: 'Case X-Ray' })).toBeVisible();
});

test('admin QR page ignores stale status responses from an older job', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('teddy_hospital_jwt', 'token-abc');
  });

  await page.route('**/api/auth/verify', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
  });

  let createdJobs = 0;
  await page.route('**/api/admin/qr-jobs', async (route, request) => {
    if (request.method() !== 'POST') {
      await route.fallback();
      return;
    }

    createdJobs += 1;
    const jobId = createdJobs === 1 ? 'job-old' : 'job-new';
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: jobId, status: 'running' })
    });
  });

  await page.route('**/api/admin/qr-jobs/job-old', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'failed', progress: 100 })
    });
  });

  await page.route('**/api/admin/qr-jobs/job-new', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'done', progress: 100 })
    });
  });

  await page.goto('/admin');
  await page.getByRole('button', { name: 'Start Job' }).click();
  await page.waitForTimeout(50);
  await page.getByRole('button', { name: 'Start Job' }).click();

  const statusLine = page.locator('p').filter({ hasText: 'Status:' });
  await expect(statusLine).toContainText('done');

  await page.waitForTimeout(1800);
  await expect(statusLine).toContainText('done');
});
