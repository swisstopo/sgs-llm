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
});
