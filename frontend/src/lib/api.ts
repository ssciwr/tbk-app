import { env } from '$env/dynamic/public';
import { writable } from 'svelte/store';

const BASE = (env.PUBLIC_BACKEND_URL || '').trim().replace(/\/$/, '');
const TOKEN_KEY = 'teddy_hospital_jwt';
const initialToken =
  typeof window === 'undefined' ? null : window.localStorage.getItem(TOKEN_KEY);

export const authToken = writable<string | null>(initialToken);

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
  authToken.set(null);
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
