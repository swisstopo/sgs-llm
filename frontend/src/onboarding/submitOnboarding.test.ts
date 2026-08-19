import { describe, expect, it, vi } from 'vitest';
import { submitOnboarding } from './submitOnboarding';

const PAYLOAD = {
  type: 'onboarding' as const,
  user_group: 'public_administration' as const,
  geodata_experience: 'advanced' as const,
  intended_use: 'professional_analysis' as const,
  consent_version: 'v2',
  lang: 'de',
};

describe('submitOnboarding', () => {
  it('POSTs the profile through the existing submission endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'entry-id' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await submitOnboarding('http://localhost:8787/feedback', PAYLOAD, fetchMock);
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:8787/feedback', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(PAYLOAD),
    });
  });

  it('rejects completion when persistence fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
    await expect(
      submitOnboarding('http://localhost:8787/feedback', PAYLOAD, fetchMock),
    ).rejects.toThrow(/503/);
  });
});
