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
