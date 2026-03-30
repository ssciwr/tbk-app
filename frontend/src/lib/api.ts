import { env } from '$env/dynamic/public';
import { writable } from 'svelte/store';
import { clearStoredCameraSelections } from '$lib/camera';

const BASE = (env.PUBLIC_BACKEND_URL || '').trim().replace(/\/$/, '');
const TOKEN_KEY = 'teddy_hospital_jwt';
const initialToken =
  typeof window === 'undefined' ? null : window.localStorage.getItem(TOKEN_KEY);

export const authToken = writable<string | null>(initialToken);

export type AppConfig = {
  fracture_editor_enabled: boolean;
};

export type RunnerStatus = {
  runner_connected: boolean;
  last_poll_at: string | null;
  stale_after_seconds: number;
};

const defaultAppConfig: AppConfig = {
  fracture_editor_enabled: true
};

let cachedAppConfig: AppConfig = { ...defaultAppConfig };
let appConfigLoaded = false;

export function tokenKey(): string {
  return TOKEN_KEY;
}

export function apiUrl(path: string): string {
  if (!path.startsWith('/')) {
    throw new Error('API path must start with /');
  }
  if (!BASE) {
    return path;
  }
  return `${BASE}${path}`;
}

export function getToken(): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  authToken.set(token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  clearStoredCameraSelections();
  authToken.set(null);
  cachedAppConfig = { ...defaultAppConfig };
  appConfigLoaded = false;
}

export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(apiUrl(path), { ...init, headers });
}

export async function authedFetchUrl(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(url, { ...init, headers });
}

export function getCachedAppConfig(): AppConfig {
  return cachedAppConfig;
}

export async function loadAppConfig(force = false): Promise<AppConfig> {
  if (!force && appConfigLoaded) {
    return cachedAppConfig;
  }

  try {
    const response = await authedFetch('/api/config');
    if (!response.ok) {
      return cachedAppConfig;
    }
    const payload = (await response.json()) as Partial<AppConfig>;
    cachedAppConfig = {
      ...defaultAppConfig,
      ...payload
    };
    appConfigLoaded = true;
  } catch {
    // Keep defaults when config endpoint is unavailable.
  }

  return cachedAppConfig;
}

export async function loadRunnerStatus(): Promise<RunnerStatus | null> {
  try {
    const response = await authedFetch('/api/worker/status', { cache: 'no-store' });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as RunnerStatus;
  } catch {
    return null;
  }
}
