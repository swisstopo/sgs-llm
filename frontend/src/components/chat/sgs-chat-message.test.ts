// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import type { AssistantChatMessage } from '../../services/ChatService';
import './sgs-chat-message';
import type { SgsChatMessage } from './sgs-chat-message';

function message(markdown: string): AssistantChatMessage {
  return {
    role: 'assistant',
    id: 'm1',
    status: 'complete',
    steps: [],
    markdown,
    catalogLayers: [{ id: 'ch.bafu.aquaprotect_100', name: 'Überschwemmung Aquaprotect 100' }],
    focusBBox: [7.2, 46.8, 7.8, 47.2],
  };
}

describe('sgs-chat-message inline catalog layers', () => {
  it('opens map choices from the layer name inside the answer', async () => {
    const element = document.createElement('sgs-chat-message') as SgsChatMessage;
    element.message = message('Öffnen Sie **Überschwemmung Aquaprotect 100**.');
    const listener = vi.fn();
    element.addEventListener('sgs-add-catalog-layer', listener);
    document.body.append(element);
    await element.updateComplete;

    const inline = element.shadowRoot?.querySelector<HTMLButtonElement>(
      'button.inline-catalog-layer',
    );
    expect(inline?.textContent).toBe('Überschwemmung Aquaprotect 100');
    expect(element.shadowRoot?.querySelector('sgs-catalog-layer-card')).toBeNull();

    inline?.click();
    await element.updateComplete;
    const choice = element.shadowRoot?.querySelector<HTMLElement>('.layer-choice');
    expect(choice).not.toBeNull();
    expect(choice?.style.left).toBe('4px');
    expect(choice?.style.top).toBe('0px');
    expect(choice?.querySelectorAll('.actions button')).toHaveLength(2);
    expect(choice?.querySelector('.close')).not.toBeNull();
    expect(choice?.querySelector('.title')?.textContent).toBe('Überschwemmung Aquaprotect 100');
    expect(choice?.querySelector('.metadata')?.textContent).toContain('ch.bafu.aquaprotect_100');
    choice?.querySelector<HTMLButtonElement>('.actions button')?.click();

    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({
      layer: element.message.catalogLayers?.[0],
      focusBBox: [7.2, 46.8, 7.8, 47.2],
    });
    element.remove();
  });

  it('offers removal when the layer is already on the map', async () => {
    const element = document.createElement('sgs-chat-message') as SgsChatMessage;
    element.message = message('Öffnen Sie **Überschwemmung Aquaprotect 100**.');
    element.addedLayerIds = new Set(['ch.bafu.aquaprotect_100']);
    const listener = vi.fn();
    element.addEventListener('sgs-remove-catalog-layer', listener);
    document.body.append(element);
    await element.updateComplete;

    element.shadowRoot?.querySelector<HTMLButtonElement>('button.inline-catalog-layer')?.click();
    await element.updateComplete;
    element.shadowRoot?.querySelector<HTMLButtonElement>('.layer-choice .actions button')?.click();

    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({ id: 'ch.bafu.aquaprotect_100' });
    element.remove();
  });

  it('keeps a fallback card when the model did not repeat the exact title', async () => {
    const element = document.createElement('sgs-chat-message') as SgsChatMessage;
    element.message = message('Die passende Hochwasserkarte ist verfügbar.');
    document.body.append(element);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('button.inline-catalog-layer')).toBeNull();
    expect(element.shadowRoot?.querySelector('sgs-catalog-layer-card')).not.toBeNull();
    element.remove();
  });
});
