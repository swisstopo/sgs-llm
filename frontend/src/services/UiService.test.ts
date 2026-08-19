import { describe, expect, it } from 'vitest';
import { CHAT_ONBOARDING_STORAGE_KEY, CHAT_ONBOARDING_VERSION, UiService } from './UiService';

class MemoryStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe('UiService chat onboarding', () => {
  it('opens onboarding on page load until the current version is accepted', () => {
    const storage = new MemoryStorage();
    expect(new UiService(storage).chatOnboardingOpen).toBe(true);

    storage.setItem(CHAT_ONBOARDING_STORAGE_KEY, CHAT_ONBOARDING_VERSION);
    expect(new UiService(storage).chatOnboardingOpen).toBe(false);
  });

  it('keeps onboarding open while gating chat', () => {
    const service = new UiService(new MemoryStorage());
    service.togglePanel('maps');
    service.togglePanel('chat');

    expect(service.activePanel).toBe('maps');
    expect(service.chatOnboardingOpen).toBe(true);
  });

  it('stores acceptance and opens chat', () => {
    const storage = new MemoryStorage();
    const service = new UiService(storage);
    service.togglePanel('chat');
    service.acceptChatOnboarding();

    expect(service.chatOnboardingOpen).toBe(false);
    expect(service.activePanel).toBe('chat');
    expect(storage.getItem(CHAT_ONBOARDING_STORAGE_KEY)).toBe(CHAT_ONBOARDING_VERSION);

    service.togglePanel('chat');
    expect(service.activePanel).toBeNull();
  });

  it('skips onboarding only for the current accepted version', () => {
    const storage = new MemoryStorage();
    storage.setItem(CHAT_ONBOARDING_STORAGE_KEY, CHAT_ONBOARDING_VERSION);
    const accepted = new UiService(storage);
    accepted.togglePanel('chat');
    expect(accepted.activePanel).toBe('chat');
    expect(accepted.chatOnboardingOpen).toBe(false);

    storage.setItem(CHAT_ONBOARDING_STORAGE_KEY, 'outdated');
    const outdated = new UiService(storage);
    expect(outdated.activePanel).toBeNull();
    expect(outdated.chatOnboardingOpen).toBe(true);
  });

  it('keeps acceptance for the page session when storage fails', () => {
    const storage = {
      getItem: () => null,
      setItem: () => {
        throw new Error('storage disabled');
      },
    };
    const service = new UiService(storage);
    service.togglePanel('chat');
    service.acceptChatOnboarding();
    service.togglePanel('chat');
    service.togglePanel('chat');

    expect(service.activePanel).toBe('chat');
    expect(service.chatOnboardingOpen).toBe(false);
  });
});
