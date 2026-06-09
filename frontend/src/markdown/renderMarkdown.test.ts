// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './renderMarkdown';

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
});
