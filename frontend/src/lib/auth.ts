import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import { apiUrl, clearToken, getToken } from '$lib/api';

export async function verifyToken(token: string): Promise<boolean> {
  const response = await fetch(apiUrl('/api/auth/verify'), {
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  return response.ok;
}

export async function requireAuthRedirect(): Promise<string | null> {
  if (!browser) {
    return null;
  }

  const token = getToken();
  if (!token) {
    goto('/login');
    return null;
  }

  const valid = await verifyToken(token);
  if (!valid) {
    clearToken();
    goto('/login');
    return null;
  }

  return token;
}
