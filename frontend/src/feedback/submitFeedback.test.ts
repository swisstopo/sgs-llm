import { describe, expect, it, vi } from 'vitest';
import { submitFeedback } from './submitFeedback';

const PAYLOAD = {
  category: 'bug' as const,
  message: 'The map is upside down',
  email: 'test@example.ch',
  lang: 'de',
};

describe('submitFeedback', () => {
  it('POSTs the payload as JSON and resolves on 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    await submitFeedback('http://localhost:8787/feedback', PAYLOAD, fetchMock);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8787/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(PAYLOAD),
    });
  });

  it('throws on a non-2xx response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));
    await expect(submitFeedback('http://x/feedback', PAYLOAD, fetchMock)).rejects.toThrow(/500/);
  });

  it('propagates network errors', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(submitFeedback('http://x/feedback', PAYLOAD, fetchMock)).rejects.toThrow(
      /Failed to fetch/,
    );
  });
});
