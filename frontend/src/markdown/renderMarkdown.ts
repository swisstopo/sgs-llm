import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { ensureExternalLinkHook } from './purifyLinkHook';

/** Renders agent markdown to sanitized HTML (GFM, no raw HTML passthrough). */
export function renderMarkdown(markdown: string): string {
  ensureExternalLinkHook();
  const html = marked.parse(markdown, { async: false, gfm: true, breaks: true });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'iframe', 'form', 'input'],
  });
}
