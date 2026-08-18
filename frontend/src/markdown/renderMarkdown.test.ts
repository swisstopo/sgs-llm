// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { mentionedCatalogLayers, renderMarkdown } from './renderMarkdown';

describe('renderMarkdown', () => {
  it('renders GFM markdown', () => {
    const html = renderMarkdown('## Titel\n\n- eins\n- zwei\n\n| a | b |\n| - | - |\n| 1 | 2 |');
    expect(html).toContain('<h2>');
    expect(html).toContain('<li>eins</li>');
    expect(html).toContain('<table>');
  });

  it('strips script tags and event handlers', () => {
    const html = renderMarkdown('Hello <script>alert(1)</script> <img src=x onerror=alert(1)>');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
  });

  it('forces safe link targets', () => {
    const html = renderMarkdown('[swisstopo](https://www.swisstopo.admin.ch)');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it('turns a structured official-layer title into an inline control', () => {
    const layer = { id: 'ch.bafu.aquaprotect_100', name: 'Überschwemmung Aquaprotect 100' };
    const markdown = `Klicken Sie auf **${layer.name}**, um die Ebene auszuwählen.`;

    const html = renderMarkdown(markdown, [layer]);

    expect(html).toContain('class="inline-catalog-layer"');
    expect(html).toContain(`data-catalog-layer-id="${layer.id}"`);
    expect(html).toContain(`>${layer.name}</button>`);
    expect(mentionedCatalogLayers(markdown, [layer])).toEqual([layer]);
  });

  it('does not rewrite layer-like text without a validated structured reference', () => {
    const html = renderMarkdown('ch.attacker.fake');
    expect(html).not.toContain('inline-catalog-layer');
  });

  it('replaces a model-authored layer link with the validated inline control', () => {
    const layer = { id: 'ch.bafu.aquaprotect_100', name: 'Aquaprotect' };
    const html = renderMarkdown('[Aquaprotect](ch.bafu.aquaprotect_100)', [layer]);
    expect(html).toContain('inline-catalog-layer');
    expect(html).not.toContain('<a');
  });

  it('does not rewrite layer text inside code', () => {
    const layer = { id: 'ch.bafu.aquaprotect_100', name: 'Aquaprotect' };
    const html = renderMarkdown('`Aquaprotect`', [layer]);
    expect(html).not.toContain('inline-catalog-layer');
  });
});
