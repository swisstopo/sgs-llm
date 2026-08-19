// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminRecord } from './types';
import './sgs-admin-app';

interface TestAdminElement extends HTMLElement {
  authenticated: boolean;
  kind: 'conversations' | 'profiles' | 'feedback';
  loading: boolean;
  records: AdminRecord[];
  updateComplete: Promise<boolean>;
}

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe('admin conversation records', () => {
  it('expands and collapses a complete multi-turn conversation inline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    const element = document.createElement('sgs-admin-app') as unknown as TestAdminElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    element.loading = false;
    element.authenticated = true;
    element.kind = 'conversations';
    element.records = [
      {
        conversation_id: 'conversation-1',
        started_at: '2026-08-19T10:00:00Z',
        updated_at: '2026-08-19T10:02:00Z',
        lang: 'en',
        message_count: 2,
        first_user_message: 'Show me Basel',
        models: ['test-model'],
        tools_used: ['search_locations', 'display_layer'],
        total_latency_ms: 2000,
        input_tokens: 300,
        output_tokens: 80,
        layer_count: 2,
        error_count: 1,
        turns: [
          {
            ts: '2026-08-19T10:00:00Z',
            message_id: 'message-1',
            lang: 'en',
            user_message: 'Show me Basel',
            assistant_markdown: 'Basel is shown.',
            model_id: 'test-model',
            tool_calls: ['search_locations', 'display_layer'],
            latency_ms: 1200,
            input_tokens: 180,
            output_tokens: 50,
            layer_count: 1,
          },
          {
            ts: '2026-08-19T10:02:00Z',
            message_id: 'message-2',
            lang: 'en',
            user_message: 'Now compare it with Bern',
            assistant_markdown: 'Here is the comparison.',
            model_id: 'test-model',
            tool_calls: ['search_locations'],
            latency_ms: 800,
            input_tokens: 120,
            output_tokens: 30,
            layer_count: 1,
            error_code: 'partial_result',
          },
        ],
      },
    ];
    await element.updateComplete;

    const root = element.shadowRoot;
    const disclosure = root?.querySelector<HTMLButtonElement>('.conversation-list-item button');
    expect(disclosure?.getAttribute('aria-expanded')).toBe('false');
    expect(root?.querySelector('.inline-transcript')).toBeNull();

    disclosure?.click();
    await element.updateComplete;
    expect(disclosure?.getAttribute('aria-expanded')).toBe('true');
    expect(root?.querySelectorAll('.conversation-turn')).toHaveLength(2);
    expect(root?.querySelector('.inline-transcript')?.textContent).toContain(
      'Now compare it with Bern',
    );
    const expandedText = root?.querySelector('.inline-transcript')?.textContent ?? '';
    expect(expandedText).toContain('conversation-1');
    expect(expandedText).toContain('message-2');
    expect(expandedText).toContain('test-model');
    expect(expandedText).toContain('display_layer');
    expect(expandedText).toContain('300');
    expect(expandedText).toContain('80');
    expect(expandedText).toContain('partial_result');

    disclosure?.click();
    await element.updateComplete;
    expect(root?.querySelector('.inline-transcript')).toBeNull();
  });
});
