import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchJson, fetchText } from './http';

describe('fetchJson / fetchText', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('returns parsed JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: 1 }))));
    expect(await fetchJson('https://example.test/x')).toEqual({ ok: 1 });
  });

  it('returns text on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<div>legend</div>')));
    expect(await fetchText('https://example.test/legend')).toBe('<div>legend</div>');
  });

  it('throws with status on non-2xx', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    await expect(fetchJson('https://example.test/x?secret=1')).rejects.toThrow(/503/);
    // The query string must not leak into the error message.
    await expect(fetchJson('https://example.test/x?secret=1')).rejects.not.toThrow(/secret/);
  });

  it('aborts via the caller signal', async () => {
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    const pending = fetchJson('https://example.test/slow', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow(/abort/i);
  });

  it('aborts after the timeout', async () => {
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('TimedOut', 'TimeoutError')),
          );
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const pending = fetchJson('https://example.test/slow', { timeoutMs: 20 });
    await expect(pending).rejects.toThrow(/time/i);
  });
});
