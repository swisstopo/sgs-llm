// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { sanitizeLegendHtml } from './sanitizeLegend';

describe('sanitizeLegendHtml', () => {
  it('keeps legend swatch images', () => {
    const html = sanitizeLegendHtml(
      '<div class="legend"><img src="//api3.geo.admin.ch/static/images/legends/x.png"> Low</div>',
    );
    expect(html).toContain('<img');
    expect(html).toContain('//api3.geo.admin.ch/static/images/legends/x.png');
    expect(html).toContain('Low');
  });

  it('strips scripts and inline event handlers', () => {
    const html = sanitizeLegendHtml('<script>alert(1)</script><img src=x onerror=alert(1)>');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
  });

  it('keeps metadata links and forces them to open safely in a new tab', () => {
    // Real-world fragment shape: the API uses target="new".
    const html = sanitizeLegendHtml(
      '<a target="new" href="https://www.geocat.ch/datahub/dataset/x">geocat</a>',
    );
    expect(html).toContain('href="https://www.geocat.ch/datahub/dataset/x"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});

describe('renderMarkdown link handling (shared hook regression)', () => {
  it('still opens markdown links in a new tab', async () => {
    const { renderMarkdown } = await import('./renderMarkdown');
    const html = renderMarkdown('[swisstopo](https://www.swisstopo.admin.ch)');
    expect(html).toContain('href="https://www.swisstopo.admin.ch"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
