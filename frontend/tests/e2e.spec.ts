import { expect, test } from '@playwright/test';

const TINY_PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMBAAImfukAAAAASUVORK5CYII=';

test('login flow stores token and redirects to camera', async ({ page }) => {
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

  await expect(page).toHaveURL(/\/camera$/);
  await expect(page.getByText('Case Details')).toBeVisible();
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

  await page.goto('/results');
  await expect(page.getByText('Case #1')).toBeVisible();

  await page.getByRole('button', { name: 'Accept' }).first().click();
  await expect(page.getByText('Case 1: confirm applied.')).toBeVisible();
});
