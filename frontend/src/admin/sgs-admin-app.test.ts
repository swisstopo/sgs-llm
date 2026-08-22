// @vitest-environment jsdom

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../i18n/i18n';
import type { AdminMetrics, AdminRecord } from './types';
import './sgs-admin-app';

interface TestAdminElement extends HTMLElement {
  authenticated: boolean;
  kind: 'conversations' | 'profiles' | 'feedback';
  loading: boolean;
  metrics?: AdminMetrics;
  records: AdminRecord[];
  updateComplete: Promise<boolean>;
}

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});

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

describe('admin profile records', () => {
  it('renders each submitted onboarding form as one row with every answer in its column', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    const element = document.createElement('sgs-admin-app') as unknown as TestAdminElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    element.loading = false;
    element.authenticated = true;
    element.kind = 'profiles';
    element.metrics = {
      from: '2026-08-19',
      to: '2026-08-19',
      daily: [],
      totals: { onboarding: 2 },
      breakdowns: {
        user_groups: { private_sector: 1, public_administration: 1 },
        geodata_experience: { occasional: 1, advanced: 1 },
        intended_uses: { create_map: 1, find_data: 1 },
      },
    };
    element.records = [
      {
        id: 'profile-1',
        entry_type: 'onboarding',
        ts: '2026-08-19T10:00:00Z',
        lang: 'en',
        user_group: 'private_sector',
        geodata_experience: 'occasional',
        intended_use: 'create_map',
        consent_version: 'v2',
      },
      {
        id: 'profile-2',
        entry_type: 'onboarding',
        ts: '2026-08-19T11:00:00Z',
        lang: 'de',
        user_group: 'public_administration',
        geodata_experience: 'advanced',
        intended_use: 'find_data',
        consent_version: 'v2',
      },
    ];
    await element.updateComplete;

    const root = element.shadowRoot;
    const headers = [...(root?.querySelectorAll('.record-header.profile-grid span') ?? [])].map(
      (cell) => cell.textContent?.trim(),
    );
    expect(headers).toEqual([
      'Submitted',
      'Language',
      'User type',
      'Geodata experience',
      'Main purpose',
      'Consent',
    ]);

    const rows = root?.querySelectorAll<HTMLButtonElement>('.profile-record');
    expect(rows).toHaveLength(2);
    const firstRow = rows?.[0]?.textContent ?? '';
    expect(firstRow).toContain('Private sector');
    expect(firstRow).toContain('I use geodata occasionally');
    expect(firstRow).toContain('Create or enrich a map');
    expect(firstRow).toContain('v2');
    expect(firstRow).not.toContain('private_sector');
    expect(firstRow).not.toContain('create_map');

    expect(root?.querySelector('.survey-total')?.textContent).toContain('2 responses');
    expect(root?.querySelectorAll('.survey-histogram')).toHaveLength(3);
    expect(root?.querySelectorAll('.histogram-row')).toHaveLength(13);
    expect(root?.querySelector('.survey-histogram h4')?.textContent).toBe(
      'Which best describes you?',
    );
    const selectedOption = root
      ?.querySelector('[title="Private sector"]')
      ?.closest('.histogram-row');
    expect(selectedOption?.querySelector('.histogram-count')?.textContent).toBe('1');
    expect(selectedOption?.querySelector<HTMLElement>('.histogram-bar')?.style.width).toBe('100%');
    const unselectedOption = root
      ?.querySelector('[title="Private individual"]')
      ?.closest('.histogram-row');
    expect(unselectedOption?.querySelector('.histogram-count')?.textContent).toBe('0');
    expect(unselectedOption?.querySelector<HTMLElement>('.histogram-bar')?.style.width).toBe('0%');
  });

  it('shows "No answer" for optional survey questions left blank', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    const element = document.createElement('sgs-admin-app') as unknown as TestAdminElement;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    element.loading = false;
    element.authenticated = true;
    element.kind = 'profiles';
    element.metrics = {
      from: '2026-08-22',
      to: '2026-08-22',
      daily: [],
      totals: { onboarding: 1 },
      breakdowns: {
        user_groups: { unknown: 1 },
        geodata_experience: { new: 1 },
        intended_uses: { unknown: 1 },
      },
    };
    element.records = [
      {
        id: 'profile-3',
        entry_type: 'onboarding',
        ts: '2026-08-22T10:00:00Z',
        lang: 'fr',
        geodata_experience: 'new',
        consent_version: 'v2',
      },
    ];
    await element.updateComplete;

    const root = element.shadowRoot;
    const row = root?.querySelector('.profile-record')?.textContent ?? '';
    expect(row).toContain('No answer');
    expect(row).toContain('I am new to geodata');
    expect(row).not.toContain('unknown');

    // Known options always render; the "No answer" row appears only where it has a count.
    expect(root?.querySelectorAll('.histogram-row')).toHaveLength(15);
    const unanswered = root?.querySelector('[title="No answer"]')?.closest('.histogram-row');
    expect(unanswered?.querySelector('.histogram-count')?.textContent).toBe('1');
    expect(unanswered?.querySelector<HTMLElement>('.histogram-bar')?.style.width).toBe('100%');
  });
});
