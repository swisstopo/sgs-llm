import { getRuntimeConfig } from '../config';

export async function signIn(email: string, password: string): Promise<void> {
  const response = await adminFetch('/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error('Invalid email or password');
}

export async function logout(): Promise<void> {
  await adminFetch('/logout', { method: 'POST' });
}

export async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${getRuntimeConfig().adminApiUrl}${path}`, {
    ...init,
    credentials: 'include',
  });
}
