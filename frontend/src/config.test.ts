import { describe, expect, it } from 'vitest';
import { mergeConfig } from './config';

describe('mergeConfig', () => {
  it('returns defaults for non-object input', () => {
    expect(mergeConfig(null).agentWsUrl).toBe('ws://localhost:8787/ws/v1');
    expect(mergeConfig('nope').agentWsUrl).toBe('ws://localhost:8787/ws/v1');
  });

  it('keeps a valid agentWsUrl', () => {
    expect(mergeConfig({ agentWsUrl: 'wss://agent.example.ch/ws/v1' }).agentWsUrl).toBe(
      'wss://agent.example.ch/ws/v1',
    );
  });

  it('falls back when agentWsUrl is empty or wrongly typed', () => {
    expect(mergeConfig({ agentWsUrl: '' }).agentWsUrl).toBe('ws://localhost:8787/ws/v1');
    expect(mergeConfig({ agentWsUrl: 42 }).agentWsUrl).toBe('ws://localhost:8787/ws/v1');
  });

  it('merges feedbackUrl with default fallback', () => {
    expect(mergeConfig({ feedbackUrl: 'https://agent.example.ch/feedback' }).feedbackUrl).toBe(
      'https://agent.example.ch/feedback',
    );
    expect(mergeConfig({}).feedbackUrl).toBe('http://localhost:8787/feedback');
  });
});
