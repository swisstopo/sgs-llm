import { afterEach, describe, expect, it, vi } from 'vitest';
import { adminFetch, logout, signIn } from './auth';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('local admin authentication', () => {
  it('posts email and password and includes the HTTP-only session cookie', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);

    await signIn('admin@example.ch', 'CorrectHorse!1');

    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8787/admin/api/login',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ email: 'admin@example.ch', password: 'CorrectHorse!1' }),
      }),
    );
  });

  it('rejects failed login and sends logout through the same API', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockResolvedValueOnce(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);

    await expect(signIn('admin@example.ch', 'wrong')).rejects.toThrow();
    await logout();
    expect(fetch).toHaveBeenLastCalledWith(
      'http://localhost:8787/admin/api/logout',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    );
  });

  it('always includes credentials on protected reads', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    await adminFetch('/me');
    expect(fetch).toHaveBeenCalledWith(
      'http://localhost:8787/admin/api/me',
      expect.objectContaining({ credentials: 'include' }),
    );
  });
});
