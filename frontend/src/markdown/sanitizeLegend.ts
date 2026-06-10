import DOMPurify from 'dompurify';

/**
 * Sanitizes an untrusted legend HTML fragment from the Swisstopo API for
 * inline rendering. Keeps the swatch `<img>`s and table markup but strips
 * scripts, styles, and embedded frames. Image URLs in the fragment are
 * protocol-relative (`//api3.geo.admin.ch/…`) and resolve against the page.
 */
export function sanitizeLegendHtml(raw: string): string {
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'script', 'form', 'input'],
  });
}
